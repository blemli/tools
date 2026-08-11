# kd — shell glue for the kd tool (blemli/tools)
# Source from .zshrc:  source ~/git/tools/kd/kd.zsh
# All logic lives in kd.py; this file only provides what has to be shell:
# the kamal() wrapper, the prompt badge, aliases and tab completion.

# kamal wrapper: destination injection, production guard, local docker mode
kamal() { kd run "$@" }

alias kdenv='kd env'
alias kamo='kd open'
alias getdb='kd getdb'

# Prompt: show destination badge on the right (only in Kamal projects).
# Pure zsh — this runs on every prompt, so no python here. Reads the same
# per-project state files kd.py writes (~/.config/kd/dest/<path-encoded-root>).
_kd_prompt_precmd() {
  local root=$(git rev-parse --show-toplevel 2>/dev/null)
  if [[ -z "$root" || ! -f "$root/config/deploy.yml" || ! -d "$root/.kamal" ]]; then
    RPROMPT=""
    return
  fi

  local dest="" f="$HOME/.config/kd/dest/${root//\//%}"
  [[ -f "$f" ]] && dest=$(<"$f")
  local -a dests=( "$root"/config/deploy.*.yml(N) )

  if [[ "$dest" == "production" ]]; then
    RPROMPT="%K{red}%F{white}%B PRODUCTION %b%f%k"
  elif [[ "$dest" == "local" ]]; then
    RPROMPT="%K{blue}%F{white} local %f%k"
  elif [[ -n "$dest" ]]; then
    RPROMPT="%K{yellow}%F{black} $dest %f%k"
  elif (( ${#dests} == 0 )); then
    # No destination configs — deploy.yml used directly (production)
    RPROMPT="%K{red}%F{white}%B PRODUCTION %b%f%k"
  else
    RPROMPT=""
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _kd_prompt_precmd

# Tab completion (click). Generated once and cached; delete the cache file
# to regenerate after a click upgrade.
_kd_comp_cache="${0:A:h}/.kd-complete.zsh"
if [[ ! -f "$_kd_comp_cache" ]] && (( $+commands[kd] )); then
  _KD_COMPLETE=zsh_source kd > "$_kd_comp_cache" 2>/dev/null || rm -f "$_kd_comp_cache"
fi
[[ -f "$_kd_comp_cache" ]] && (( $+functions[compdef] )) && source "$_kd_comp_cache"
