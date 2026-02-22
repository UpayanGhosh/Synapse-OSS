
_openclaw_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    # Simple top-level completion for now
    opts="setup onboard configure config doctor dashboard reset uninstall message memory agent agents status health sessions browser completion acp gateway daemon logs system models approvals nodes devices node sandbox tui cron dns docs hooks webhooks pairing plugins channels directory security skills update -V, --dev --profile --no-color"
    
    case "${prev}" in
      setup)
        opts=" --workspace --wizard --non-interactive --mode --remote-url --remote-token"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      onboard)
        opts=" --workspace --reset --non-interactive --accept-risk --flow --mode --auth-choice --token-provider --token --token-profile-id --token-expires-in --anthropic-api-key --openai-api-key --openrouter-api-key --ai-gateway-api-key --cloudflare-ai-gateway-account-id --cloudflare-ai-gateway-gateway-id --cloudflare-ai-gateway-api-key --moonshot-api-key --kimi-code-api-key --gemini-api-key --zai-api-key --xiaomi-api-key --minimax-api-key --synthetic-api-key --venice-api-key --opencode-zen-api-key --xai-api-key --qianfan-api-key --gateway-port --gateway-bind --gateway-auth --gateway-token --gateway-password --remote-url --remote-token --tailscale --tailscale-reset-on-exit --install-daemon --no-install-daemon --skip-daemon --daemon-runtime --skip-channels --skip-skills --skip-health --skip-ui --node-manager --json"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      configure)
        opts=" --section"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      config)
        opts="get set unset --section"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      doctor)
        opts=" --no-workspace-suggestions --yes --repair --fix --force --non-interactive --generate-gateway-token --deep"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      dashboard)
        opts=" --no-open"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      reset)
        opts=" --scope --yes --non-interactive --dry-run"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      uninstall)
        opts=" --service --state --workspace --app --all --yes --non-interactive --dry-run"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      message)
        opts="send broadcast poll react reactions read edit delete pin unpin pins permissions search thread emoji sticker role channel member voice event timeout kick ban "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      memory)
        opts="status index search "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      agent)
        opts=" -m, -t, --session-id --agent --thinking --verbose --channel --reply-to --reply-channel --reply-account --local --deliver --json --timeout"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      agents)
        opts="list add set-identity delete "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      status)
        opts=" --json --all --usage --deep --timeout --verbose --debug"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      health)
        opts=" --json --timeout --verbose --debug"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      sessions)
        opts=" --json --verbose --store --active"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      browser)
        opts="status start stop reset-profile tabs tab open focus close profiles create-profile delete-profile extension screenshot snapshot navigate resize click type press hover scrollintoview drag select upload waitfordownload download dialog fill wait evaluate console pdf responsebody highlight errors requests trace cookies storage set --browser-profile --json --url --token --timeout --expect-final"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      completion)
        opts=" -s, -i, --write-state -y,"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      acp)
        opts="client --url --token --password --session --session-label --require-existing --reset-session --no-prefix-cwd --verbose,"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      gateway)
        opts="run status install uninstall start stop restart call usage-cost health probe discover --port --bind --token --auth --password --tailscale --tailscale-reset-on-exit --allow-unconfigured --dev --reset --force --verbose --claude-cli-logs --ws-log --compact --raw-stream --raw-stream-path"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      daemon)
        opts="status install uninstall start stop restart "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      logs)
        opts=" --limit --max-bytes --follow --interval --json --plain --no-color --url --token --timeout --expect-final"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      system)
        opts="event heartbeat presence "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      models)
        opts="list status set set-image aliases fallbacks image-fallbacks scan auth --status-json --status-plain --agent"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      approvals)
        opts="get set allowlist "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      nodes)
        opts="status describe list pending approve reject rename invoke run notify canvas camera screen location "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      devices)
        opts="list approve reject rotate revoke "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      node)
        opts="run status install uninstall stop restart "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      sandbox)
        opts="list recreate explain "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      tui)
        opts=" --url --token --password --session --deliver --thinking --message --timeout-ms --history-limit"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      cron)
        opts="status list add rm enable disable runs run edit "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      dns)
        opts="setup "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      docs)
        opts=" "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      hooks)
        opts="list info check enable disable install update "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      webhooks)
        opts="gmail "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      pairing)
        opts="list approve "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      plugins)
        opts="list info enable disable install update doctor "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      channels)
        opts="list status capabilities resolve logs add remove login logout "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      directory)
        opts="self peers groups "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      security)
        opts="audit "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      skills)
        opts="list info check "
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
      update)
        opts="wizard status --json --no-restart --channel --tag --timeout --yes"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
        ;;
    esac

    if [[ ${cur} == -* ]] ; then
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
    fi
    
    COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
}

complete -F _openclaw_completion openclaw
