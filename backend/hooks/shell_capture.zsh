# ADDGate shell capture for zsh.
#
# Records each command you run (the command, the folder, the exit code, the time) so ADDGate
# can quiz you on your own work, not just Claude's. Command OUTPUT is never recorded.
#
# - Does nothing unless capture is turned on in ADDGate (it checks ~/gate/shell/.enabled).
# - Start a command with a SPACE and it's never recorded (same as zsh's HIST_IGNORE_SPACE).
# - Writes to ~/gate/shell/ with owner-only permissions. ADDGate redacts secrets and deletes
#   the raw file within seconds when it imports it.
# - Uses only zsh builtins, so it adds no noticeable delay to your prompt.
#
# ADDGate's built-in terminal loads this automatically. To also capture commands from your
# regular Terminal app, add this line to ~/.zshrc (or use Settings > Shell capture):
#   source "/path/to/ADDGate/backend/hooks/shell_capture.zsh"

[[ -n ${ADDGATE_SHELL_HOOKED-} ]] && return 0
typeset -g ADDGATE_SHELL_HOOKED=1
typeset -g __ag_dir="${ADDGATE_HOME:-$HOME/gate}/shell"
typeset -g __ag_cmd="" __ag_start="" __ag_pwd=""
zmodload zsh/datetime 2>/dev/null || return 0

__ag_preexec() {
  __ag_cmd=""
  [[ -e $__ag_dir/.enabled ]] || return 0      # capture is off
  [[ $1 == ' '* ]] && return 0                  # leading space: never record
  __ag_cmd=$1
  __ag_start=$EPOCHREALTIME
  __ag_pwd=$PWD
}

__ag_precmd() {
  local ec=$?
  [[ -n $__ag_cmd ]] || return 0
  # Fields separated by \x1f, records by \x1e: safe for commands with tabs or newlines.
  ( umask 077
    print -rn -- "${__ag_start}"$'\x1f'"${EPOCHREALTIME}"$'\x1f'"${ec}"$'\x1f'"${__ag_pwd}"$'\x1f'"${ADDGATE_TERMINAL:-0}"$'\x1f'"${__ag_cmd}"$'\x1e' \
      >> "$__ag_dir/$(strftime %Y-%m-%d $EPOCHSECONDS).log" ) 2>/dev/null
  __ag_cmd=""
  return 0
}

autoload -Uz add-zsh-hook
add-zsh-hook preexec __ag_preexec
# Run FIRST among prompt hooks so themes can't overwrite the exit code ($?) before we read it.
precmd_functions=(__ag_precmd ${precmd_functions:#__ag_precmd})
