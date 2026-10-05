# Amadeus Architecture & Module Contracts

This document is the **source of truth for module interfaces**. Contributors (human or AI)
must implement against these signatures so modules integrate without surprises.
Implemented contracts: `paths.py`, `util.py`, `tools/base.py` (read them first).

## Global rules

- Python 3.12, **synchronous** code (httpx sync streaming). Ctrl+C = `KeyboardInterrupt`.
- **All paths via `amadeus.paths`** – never `~`, `Path.home()`, `%APPDATA%`, or `tempfile` for persistent data.
- Windows-first, but keep code OS-agnostic (`os.name == "nt"` branches where needed).
- Any PowerShell invocation uses `powershell -NoProfile -NonInteractive` (the author's profile prints a large banner).
- Keep imports lazy in `cli.py` (startup speed); heavy modules imported inside functions.
- Dependencies allowed: `httpx rich prompt_toolkit typer pydantic tomli-w` + stdlib (`tomllib`). Dev: `pytest ruff respx pillow`. Do not add others.
- Tests in `tests/test_<module>.py`, must not need network, GPU or a real model. Use `tmp_path` and `monkeypatch.setenv("AMADEUS_HOME", str(tmp_path))`.
- Lint: `ruff check` + `ruff format`, line length 100.

## Dev commands (run from repo root, PowerShell)

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.runtime\venv"
uv run pytest -q tests/test_<module>.py
uv run ruff check src tests ; uv run ruff format src tests
```

## Module map & owners of each contract

```
src/amadeus/
  paths.py util.py tools/base.py         (done)
  config.py                              Settings + ModelProfile + registry
  ui.py  persona/*.md  assets/banner*.txt
  safety.py                              Policy (approval + denylist)
  tools/shell.py files.py search.py web.py memory_tools.py
  memory.py
  runtime/base.py llamacpp.py ollama.py openai_compat.py hf.py manager.py
  llm/client.py llm/toolparse.py
  context.py agent.py sessions.py doctor.py repl.py cli.py __main__.py
```

---

### config.py

```python
class ModelProfile(BaseModel):
    name: str
    description: str = ""
    repo: str | None = None          # Hugging Face repo, e.g. "Qwen/Qwen3-8B-GGUF"
    file: str | None = None          # GGUF filename inside repo
    path: str | None = None          # local GGUF path (absolute or relative to root) - overrides repo/file
    ollama: str | None = None        # Ollama tag, used when backend == "ollama"
    ctx: int = 16384
    ngl: int = 99                    # GPU layers
    n_cpu_moe: int | None = None     # MoE expert layers kept on CPU
    tools: Literal["native", "text"] = "native"
    temperature: float = 0.6
    extra_args: list[str] = []       # appended to llama-server args
    min_vram_gb: float = 0           # used by doctor for recommendations

class Settings(BaseModel):
    backend: Literal["llamacpp", "ollama", "openai"] = "llamacpp"
    openai_base_url: str = "http://127.0.0.1:8080/v1"
    ollama_url: str = "http://127.0.0.1:11434"
    default_profile: str = "general"
    mode: Literal["ask", "auto", "yolo"] = "ask"
    persona: str = "amadeus"
    banner: bool = True
    models_dir: str | None = None
    max_steps: int = 25
    memory_core_tokens: int = 1200
    web_fetch: bool = True
    shell_timeout: int = 120

def load_settings() -> Settings                      # defaults <- data/config.toml
def save_setting(key: str, value) -> None            # writes data/config.toml (tomli_w)
def load_profiles() -> dict[str, ModelProfile]       # package models.toml <- data/models.toml
def save_user_profile(p: ModelProfile) -> None
def remove_user_profile(name: str) -> bool
def models_dir(s: Settings) -> Path                  # s.models_dir or paths.default_models_dir()
def resolve_model_path(p: ModelProfile, s: Settings) -> Path   # path or models_dir/file
```
`models.toml` format: top-level `default = "general"` and `[profiles.<name>]` tables (name injected from key).

### safety.py

```python
class Policy:
    def __init__(self, mode: str, workspace: Path, prompt: Callable[[ApprovalRequest], str] | None = None)
    mode: str                                   # mutable: "ask" | "auto" | "yolo"
    def approve(self, req: ApprovalRequest) -> bool   # pass as ToolContext.approve
def denied_reason(command: str) -> str | None   # hard denylist, applies in ALL modes
```
Rules for `approve`: `read` → True. `memory` → ask unless mode=="yolo" and not untrusted_origin; untrusted_origin always asks.
`write` → ask in "ask"; auto-approve in "auto"/"yolo" only if `req.path` inside workspace, else ask.
`exec` / `net` → ask in "ask" and "auto"; True in "yolo".
`prompt(req)` returns one of `"y" "n" "a"` ("a" = always allow this (tool, risk) for the session). Default prompt uses `ui.confirm`.

### memory.py

```python
class Memory:
    def __init__(self, directory: Path | None = None)        # default paths.memory_dir()
    def core_text(self, max_tokens: int = 1200) -> str       # profile.md + preferences.md, trimmed
    def remember(self, text: str, kind: Literal["profile","preference","note"] = "note",
                 topic: str | None = None) -> str            # returns status msg; dedups
    def recall(self, query: str, k: int = 5) -> list[str]    # keyword/BM25-lite over notes + core
    def forget(self, text: str) -> int                       # removes matching lines, returns count
    def list_topics(self) -> list[str]
```
Files: `profile.md`, `preferences.md`, `notes/<slug>.md`; entries are Markdown bullet lines `- text  <!-- 2026-10-05 -->`.

### runtime/

```python
class Backend(Protocol):            # runtime/base.py
    name: str
    def available(self) -> bool                     # binary/service present
    def start(self, profile: ModelProfile, settings: Settings) -> str   # returns OpenAI base_url ".../v1"
    def stop(self) -> None
    def model_id(self) -> str                       # value for "model" field in requests

class RuntimeManager:               # runtime/manager.py
    def __init__(self, settings: Settings, profiles: dict[str, ModelProfile], on_progress=None)
    current: ModelProfile | None
    base_url: str | None
    def switch(self, name_or_tag: str) -> str       # ensures model downloaded, stops old, starts new
    def shutdown(self) -> None
```
- `llamacpp.py`: `install(progress)` downloads latest Windows CUDA build + cudart into `paths.llamacpp_dir()`;
  spawns `llama-server` on 127.0.0.1 free port, args from profile (`-m -c -ngl --jinja -fa on --cache-type-k q8_0 --cache-type-v q8_0 [--n-cpu-moe N] [extra_args]`), waits for `GET /health` 200, logs to `paths.logs_dir()/llama-server.log`, kills process on stop/exit (Windows Job Object or atexit + terminate).
- `hf.py`: `download(repo, file, dest_dir, progress) -> Path` resumable (`Range`), writes `*.part` then renames.
- `ollama.py`: uses `/api/tags`, `/api/pull`, unload via `keep_alive: 0`; base_url `<ollama_url>/v1`.
- `openai_compat.py`: no process; base_url from settings.

### llm/

```python
@dataclass
class ToolCall: id: str; name: str; arguments: dict

@dataclass
class Delta:                         # one streamed chunk
    content: str = ""
    reasoning: str = ""              # <think> / reasoning_content, shown dimmed or hidden
    tool_calls: list[ToolCall] | None = None   # only emitted once complete (at end of stream)
    finish_reason: str | None = None

class ChatClient:                    # llm/client.py
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 600)
    def stream(self, messages: list[dict], tools: list[dict] | None = None,
               temperature: float = 0.6, tool_mode: str = "native") -> Iterator[Delta]
```
`toolparse.py`: `extract_tool_calls(text) -> tuple[str, list[ToolCall]]` for `tool_mode == "text"`
(supports `<tool_call>{json}</tool_call>` and ```json fenced {"name":..,"arguments":..}```), plus
`text_mode_instructions(tools) -> str` to append to the system prompt.

### agent.py / context.py

```python
# events yielded by Agent.run (UI renders them)
TextDelta(text) ; ReasoningDelta(text) ; ToolStart(call: ToolCall) ; ToolEnd(call, result: ToolResult)
Notice(text) ; Done(final_text: str, steps: int)

class Agent:
    def __init__(self, client_factory: Callable[[], ChatClient], ctx: ToolContext, settings, memory, profile_getter)
    history: list[dict]
    def run(self, user_text: str) -> Iterator[Event]
    def reset(self) -> None

class ContextBuilder:   # context.py
    def build_system(self, persona: str, memory_core: str, project_notes: str | None, tool_mode, tools) -> str
    def fit(self, history: list[dict], ctx_tokens: int, summarize: Callable[[list[dict]], str] | None) -> list[dict]
```

### ui.py

```python
console: rich.console.Console
def print_banner(compact: bool = False) -> None      # reads assets/banner.txt or banner_color.txt
def render_markdown(text: str) -> None
def show_diff(old: str, new: str, path: str) -> None
def confirm(req: ApprovalRequest) -> str             # returns "y" | "n" | "a"
def spinner(text: str)                               # context manager
def info(msg) / warn(msg) / error(msg)
```
