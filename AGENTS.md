# Notes for coding agents

This repository is a terminal theme: a Huawei-style opening animation (and, on macOS/Linux, a
home page and header branding) for the **Codex CLI** and **Claude Code**. It does not modify
either tool; it adds a shell function that starts them through `run.py`.

## Installing it for the user

When the user asks you to install this project ("帮我装上", "install this"):

1. Check Python: `python3 --version` (Windows: `py -3 --version` or `python --version`). 3.8+ is needed.
   No packages are required; everything is standard library.
2. From the repository root run (Windows: `py -3 install.py`):

   ```
   python3 install.py
   ```

   It installs for whichever of `codex` / `claude` is on PATH, copies the theme to
   `~/.pangu-cli-theme`, and adds a marked block to the shell startup files it detects
   (zsh, bash, fish, PowerShell). Run `python3 install.py --dry-run` first if the user wants
   to see the changes. Useful options:
   - `--apps codex` or `--apps claude` to install for one tool only.
   - `--codex-args="--no-daemon"` / `--claude-args="--dangerously-skip-permissions"` to keep
     flags the user always passes (an existing `alias codex='codex --flags'` is picked up
     automatically). Use the `=` form so the flags are not taken as installer options.
   - `--codex-command="..."` / `--claude-command="..."` if the tool is started some other way.
3. Show the installer's output to the user and tell them to open a new terminal (or
   `source ~/.zshrc` / `source ~/.bashrc`; PowerShell: open a new window). If the installer
   printed a PowerShell execution-policy note, relay it: the user has to run that command
   themselves.
4. To verify: `python3 install.py --status`.

Do not edit Codex or Claude Code configuration files, and do not change the user's existing
aliases yourself: the installer handles both.

## Uninstalling

```
python3 ~/.pangu-cli-theme/install.py --uninstall
```

## Working on the code

- `pangu/` is the runtime (standard library only, Python 3.8+). `apps.py` holds everything
  that differs between Codex and Claude Code.
- `python3 -m unittest discover -s tests` runs the tests (no terminal needed).
- `tools/` needs Pillow (and `tools/ptyshot.py` needs pyte); they are for development only.
