
Register-ArgumentCompleter -Native -CommandName openclaw -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    
    $commandElements = $commandAst.CommandElements
    $commandPath = ""
    
    # Reconstruct command path (simple approximation)
    # Skip the executable name
    for ($i = 1; $i -lt $commandElements.Count; $i++) {
        $element = $commandElements[$i].Extent.Text
        if ($element -like "-*") { break }
        if ($i -eq $commandElements.Count - 1 -and $wordToComplete -ne "") { break } # Don't include current word being typed
        $commandPath += "$element "
    }
    $commandPath = $commandPath.Trim()
    
    # Root command
    if ($commandPath -eq "") {
         $completions = @('setup','onboard','configure','config','doctor','dashboard','reset','uninstall','message','memory','agent','agents','status','health','sessions','browser','completion','acp','gateway','daemon','logs','system','models','approvals','nodes','devices','node','sandbox','tui','cron','dns','docs','hooks','webhooks','pairing','plugins','channels','directory','security','skills','update', '-V,','--dev','--profile','--no-color') 
         $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
         }
    }
    
    
            if ($commandPath -eq 'openclaw') {
                $completions = @('setup','onboard','configure','config','doctor','dashboard','reset','uninstall','message','memory','agent','agents','status','health','sessions','browser','completion','acp','gateway','daemon','logs','system','models','approvals','nodes','devices','node','sandbox','tui','cron','dns','docs','hooks','webhooks','pairing','plugins','channels','directory','security','skills','update','-V','--dev','--profile','--no-color')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw setup') {
                $completions = @('--workspace','--wizard','--non-interactive','--mode','--remote-url','--remote-token')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw onboard') {
                $completions = @('--workspace','--reset','--non-interactive','--accept-risk','--flow','--mode','--auth-choice','--token-provider','--token','--token-profile-id','--token-expires-in','--anthropic-api-key','--openai-api-key','--openrouter-api-key','--ai-gateway-api-key','--cloudflare-ai-gateway-account-id','--cloudflare-ai-gateway-gateway-id','--cloudflare-ai-gateway-api-key','--moonshot-api-key','--kimi-code-api-key','--gemini-api-key','--zai-api-key','--xiaomi-api-key','--minimax-api-key','--synthetic-api-key','--venice-api-key','--opencode-zen-api-key','--xai-api-key','--qianfan-api-key','--gateway-port','--gateway-bind','--gateway-auth','--gateway-token','--gateway-password','--remote-url','--remote-token','--tailscale','--tailscale-reset-on-exit','--install-daemon','--no-install-daemon','--skip-daemon','--daemon-runtime','--skip-channels','--skip-skills','--skip-health','--skip-ui','--node-manager','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw configure') {
                $completions = @('--section')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw config') {
                $completions = @('get','set','unset','--section')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw config get') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw config set') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw doctor') {
                $completions = @('--no-workspace-suggestions','--yes','--repair','--fix','--force','--non-interactive','--generate-gateway-token','--deep')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw dashboard') {
                $completions = @('--no-open')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw reset') {
                $completions = @('--scope','--yes','--non-interactive','--dry-run')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw uninstall') {
                $completions = @('--service','--state','--workspace','--app','--all','--yes','--non-interactive','--dry-run')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message') {
                $completions = @('send','broadcast','poll','react','reactions','read','edit','delete','pin','unpin','pins','permissions','search','thread','emoji','sticker','role','channel','member','voice','event','timeout','kick','ban')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message send') {
                $completions = @('-m','-t','--media','--buttons','--card','--reply-to','--thread-id','--gif-playback','--silent','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message broadcast') {
                $completions = @('--channel','--account','--json','--dry-run','--verbose','--targets','--message','--media')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message poll') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--poll-question','--poll-option','--poll-multi','--poll-duration-hours','-m')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message react') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--message-id','--emoji','--remove','--participant','--from-me','--target-author','--target-author-uuid')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message reactions') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--message-id','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message read') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--limit','--before','--after','--around','--include-thread')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message edit') {
                $completions = @('--message-id','-m','-t','--channel','--account','--json','--dry-run','--verbose','--thread-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message delete') {
                $completions = @('--message-id','-t','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message pin') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--message-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message unpin') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--message-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message pins') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message permissions') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message search') {
                $completions = @('--channel','--account','--json','--dry-run','--verbose','--guild-id','--query','--channel-id','--channel-ids','--author-id','--author-ids','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message thread') {
                $completions = @('create','list','reply')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message thread create') {
                $completions = @('--thread-name','-t','--channel','--account','--json','--dry-run','--verbose','--message-id','-m','--auto-archive-min')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message thread list') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose','--channel-id','--include-archived','--before','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message thread reply') {
                $completions = @('-m','-t','--channel','--account','--json','--dry-run','--verbose','--media','--reply-to')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message emoji') {
                $completions = @('list','upload')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message emoji list') {
                $completions = @('--channel','--account','--json','--dry-run','--verbose','--guild-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message emoji upload') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose','--emoji-name','--media','--role-ids')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message sticker') {
                $completions = @('send','upload')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message sticker send') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose','--sticker-id','-m')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message sticker upload') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose','--sticker-name','--sticker-desc','--sticker-tags','--media')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message role') {
                $completions = @('info','add','remove')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message role info') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message role add') {
                $completions = @('--guild-id','--user-id','--role-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message role remove') {
                $completions = @('--guild-id','--user-id','--role-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message channel') {
                $completions = @('info','list')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message channel info') {
                $completions = @('-t','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message channel list') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message member') {
                $completions = @('info')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message member info') {
                $completions = @('--user-id','--channel','--account','--json','--dry-run','--verbose','--guild-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message voice') {
                $completions = @('status')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message voice status') {
                $completions = @('--guild-id','--user-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message event') {
                $completions = @('list','create')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message event list') {
                $completions = @('--guild-id','--channel','--account','--json','--dry-run','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message event create') {
                $completions = @('--guild-id','--event-name','--start-time','--channel','--account','--json','--dry-run','--verbose','--end-time','--desc','--channel-id','--location','--event-type')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message timeout') {
                $completions = @('--guild-id','--user-id','--channel','--account','--json','--dry-run','--verbose','--duration-min','--until','--reason')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message kick') {
                $completions = @('--guild-id','--user-id','--channel','--account','--json','--dry-run','--verbose','--reason')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw message ban') {
                $completions = @('--guild-id','--user-id','--channel','--account','--json','--dry-run','--verbose','--reason','--delete-days')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw memory') {
                $completions = @('status','index','search')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw memory status') {
                $completions = @('--agent','--json','--deep','--index','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw memory index') {
                $completions = @('--agent','--force','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw memory search') {
                $completions = @('--agent','--max-results','--min-score','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agent') {
                $completions = @('-m','-t','--session-id','--agent','--thinking','--verbose','--channel','--reply-to','--reply-channel','--reply-account','--local','--deliver','--json','--timeout')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agents') {
                $completions = @('list','add','set-identity','delete')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agents list') {
                $completions = @('--json','--bindings')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agents add') {
                $completions = @('--workspace','--model','--agent-dir','--bind','--non-interactive','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agents set-identity') {
                $completions = @('--agent','--workspace','--identity-file','--from-identity','--name','--theme','--emoji','--avatar','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw agents delete') {
                $completions = @('--force','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw status') {
                $completions = @('--json','--all','--usage','--deep','--timeout','--verbose','--debug')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw health') {
                $completions = @('--json','--timeout','--verbose','--debug')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw sessions') {
                $completions = @('--json','--verbose','--store','--active')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser') {
                $completions = @('status','start','stop','reset-profile','tabs','tab','open','focus','close','profiles','create-profile','delete-profile','extension','screenshot','snapshot','navigate','resize','click','type','press','hover','scrollintoview','drag','select','upload','waitfordownload','download','dialog','fill','wait','evaluate','console','pdf','responsebody','highlight','errors','requests','trace','cookies','storage','set','--browser-profile','--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser tab') {
                $completions = @('new','select','close')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser create-profile') {
                $completions = @('--name','--color','--cdp-url','--driver')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser delete-profile') {
                $completions = @('--name')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser extension') {
                $completions = @('install','path')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser screenshot') {
                $completions = @('--full-page','--ref','--element','--type')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser snapshot') {
                $completions = @('--format','--target-id','--limit','--mode','--efficient','--interactive','--compact','--depth','--selector','--frame','--labels','--out')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser navigate') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser resize') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser click') {
                $completions = @('--target-id','--double','--button','--modifiers')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser type') {
                $completions = @('--submit','--slowly','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser press') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser hover') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser scrollintoview') {
                $completions = @('--target-id','--timeout-ms')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser drag') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser select') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser upload') {
                $completions = @('--ref','--input-ref','--element','--target-id','--timeout-ms')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser waitfordownload') {
                $completions = @('--target-id','--timeout-ms')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser download') {
                $completions = @('--target-id','--timeout-ms')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser dialog') {
                $completions = @('--accept','--dismiss','--prompt','--target-id','--timeout-ms')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser fill') {
                $completions = @('--fields','--fields-file','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser wait') {
                $completions = @('--time','--text','--text-gone','--url','--load','--fn','--timeout-ms','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser evaluate') {
                $completions = @('--fn','--ref','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser console') {
                $completions = @('--level','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser pdf') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser responsebody') {
                $completions = @('--target-id','--timeout-ms','--max-chars')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser highlight') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser errors') {
                $completions = @('--clear','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser requests') {
                $completions = @('--filter','--clear','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser trace') {
                $completions = @('start','stop')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser trace start') {
                $completions = @('--target-id','--no-screenshots','--no-snapshots','--sources')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser trace stop') {
                $completions = @('--out','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser cookies') {
                $completions = @('set','clear','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser cookies set') {
                $completions = @('--url','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser cookies clear') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage') {
                $completions = @('local','session')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage local') {
                $completions = @('get','set','clear')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage local get') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage local set') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage local clear') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage session') {
                $completions = @('get','set','clear')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage session get') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage session set') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser storage session clear') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set') {
                $completions = @('viewport','offline','headers','credentials','geo','media','timezone','locale','device')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set viewport') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set offline') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set headers') {
                $completions = @('--json','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set credentials') {
                $completions = @('--clear','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set geo') {
                $completions = @('--clear','--accuracy','--origin','--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set media') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set timezone') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set locale') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw browser set device') {
                $completions = @('--target-id')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw completion') {
                $completions = @('-s','-i','--write-state','-y')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw acp') {
                $completions = @('client','--url','--token','--password','--session','--session-label','--require-existing','--reset-session','--no-prefix-cwd','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw acp client') {
                $completions = @('--cwd','--server','--server-args','--server-verbose','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway') {
                $completions = @('run','status','install','uninstall','start','stop','restart','call','usage-cost','health','probe','discover','--port','--bind','--token','--auth','--password','--tailscale','--tailscale-reset-on-exit','--allow-unconfigured','--dev','--reset','--force','--verbose','--claude-cli-logs','--ws-log','--compact','--raw-stream','--raw-stream-path')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway run') {
                $completions = @('--port','--bind','--token','--auth','--password','--tailscale','--tailscale-reset-on-exit','--allow-unconfigured','--dev','--reset','--force','--verbose','--claude-cli-logs','--ws-log','--compact','--raw-stream','--raw-stream-path')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway status') {
                $completions = @('--url','--token','--password','--timeout','--no-probe','--deep','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway install') {
                $completions = @('--port','--runtime','--token','--force','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway uninstall') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway start') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway stop') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway restart') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway call') {
                $completions = @('--params','--url','--token','--password','--timeout','--expect-final','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway usage-cost') {
                $completions = @('--days','--url','--token','--password','--timeout','--expect-final','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway health') {
                $completions = @('--url','--token','--password','--timeout','--expect-final','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway probe') {
                $completions = @('--url','--ssh','--ssh-identity','--ssh-auto','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw gateway discover') {
                $completions = @('--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon') {
                $completions = @('status','install','uninstall','start','stop','restart')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon status') {
                $completions = @('--url','--token','--password','--timeout','--no-probe','--deep','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon install') {
                $completions = @('--port','--runtime','--token','--force','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon uninstall') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon start') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon stop') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw daemon restart') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw logs') {
                $completions = @('--limit','--max-bytes','--follow','--interval','--json','--plain','--no-color','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system') {
                $completions = @('event','heartbeat','presence')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system event') {
                $completions = @('--text','--mode','--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system heartbeat') {
                $completions = @('last','enable','disable')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system heartbeat last') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system heartbeat enable') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system heartbeat disable') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw system presence') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models') {
                $completions = @('list','status','set','set-image','aliases','fallbacks','image-fallbacks','scan','auth','--status-json','--status-plain','--agent')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models list') {
                $completions = @('--all','--local','--provider','--json','--plain')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models status') {
                $completions = @('--json','--plain','--check','--probe','--probe-provider','--probe-profile','--probe-timeout','--probe-concurrency','--probe-max-tokens','--agent')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models aliases') {
                $completions = @('list','add','remove')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models aliases list') {
                $completions = @('--json','--plain')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models fallbacks') {
                $completions = @('list','add','remove','clear')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models fallbacks list') {
                $completions = @('--json','--plain')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models image-fallbacks') {
                $completions = @('list','add','remove','clear')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models image-fallbacks list') {
                $completions = @('--json','--plain')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models scan') {
                $completions = @('--min-params','--max-age-days','--provider','--max-candidates','--timeout','--concurrency','--no-probe','--yes','--no-input','--set-default','--set-image','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth') {
                $completions = @('add','login','setup-token','paste-token','login-github-copilot','order','--agent')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth login') {
                $completions = @('--provider','--method','--set-default')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth setup-token') {
                $completions = @('--provider','--yes')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth paste-token') {
                $completions = @('--provider','--profile-id','--expires-in')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth login-github-copilot') {
                $completions = @('--profile-id','--yes')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth order') {
                $completions = @('get','set','clear')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth order get') {
                $completions = @('--provider','--agent','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth order set') {
                $completions = @('--provider','--agent')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw models auth order clear') {
                $completions = @('--provider','--agent')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals') {
                $completions = @('get','set','allowlist')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals get') {
                $completions = @('--node','--gateway','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals set') {
                $completions = @('--node','--gateway','--file','--stdin','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals allowlist') {
                $completions = @('add','remove')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals allowlist add') {
                $completions = @('--node','--gateway','--agent','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw approvals allowlist remove') {
                $completions = @('--node','--gateway','--agent','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes') {
                $completions = @('status','describe','list','pending','approve','reject','rename','invoke','run','notify','canvas','camera','screen','location')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes status') {
                $completions = @('--connected','--last-connected','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes describe') {
                $completions = @('--node','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes list') {
                $completions = @('--connected','--last-connected','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes pending') {
                $completions = @('--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes approve') {
                $completions = @('--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes reject') {
                $completions = @('--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes rename') {
                $completions = @('--node','--name','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes invoke') {
                $completions = @('--node','--command','--params','--invoke-timeout','--idempotency-key','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes run') {
                $completions = @('--node','--cwd','--env','--raw','--agent','--ask','--security','--command-timeout','--needs-screen-recording','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes notify') {
                $completions = @('--node','--title','--body','--sound','--priority','--delivery','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas') {
                $completions = @('snapshot','present','hide','navigate','eval','a2ui')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas snapshot') {
                $completions = @('--node','--format','--max-width','--quality','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas present') {
                $completions = @('--node','--target','--x','--y','--width','--height','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas hide') {
                $completions = @('--node','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas navigate') {
                $completions = @('--node','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas eval') {
                $completions = @('--js','--node','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas a2ui') {
                $completions = @('push','reset')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas a2ui push') {
                $completions = @('--jsonl','--text','--node','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes canvas a2ui reset') {
                $completions = @('--node','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes camera') {
                $completions = @('list','snap','clip')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes camera list') {
                $completions = @('--node','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes camera snap') {
                $completions = @('--node','--facing','--device-id','--max-width','--quality','--delay-ms','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes camera clip') {
                $completions = @('--node','--facing','--device-id','--duration','--no-audio','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes screen') {
                $completions = @('record')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes screen record') {
                $completions = @('--node','--screen','--duration','--fps','--no-audio','--out','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes location') {
                $completions = @('get')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw nodes location get') {
                $completions = @('--node','--max-age','--accuracy','--location-timeout','--invoke-timeout','--url','--token','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices') {
                $completions = @('list','approve','reject','rotate','revoke')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices list') {
                $completions = @('--url','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices approve') {
                $completions = @('--url','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices reject') {
                $completions = @('--url','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices rotate') {
                $completions = @('--device','--role','--scope','--url','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw devices revoke') {
                $completions = @('--device','--role','--url','--token','--password','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node') {
                $completions = @('run','status','install','uninstall','stop','restart')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node run') {
                $completions = @('--host','--port','--tls','--tls-fingerprint','--node-id','--display-name')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node status') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node install') {
                $completions = @('--host','--port','--tls','--tls-fingerprint','--node-id','--display-name','--runtime','--force','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node uninstall') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node stop') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw node restart') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw sandbox') {
                $completions = @('list','recreate','explain')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw sandbox list') {
                $completions = @('--json','--browser')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw sandbox recreate') {
                $completions = @('--all','--session','--agent','--browser','--force')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw sandbox explain') {
                $completions = @('--session','--agent','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw tui') {
                $completions = @('--url','--token','--password','--session','--deliver','--thinking','--message','--timeout-ms','--history-limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron') {
                $completions = @('status','list','add','rm','enable','disable','runs','run','edit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron status') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron list') {
                $completions = @('--all','--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron add') {
                $completions = @('--name','--description','--disabled','--delete-after-run','--keep-after-run','--agent','--session','--wake','--at','--every','--cron','--tz','--system-event','--message','--thinking','--model','--timeout-seconds','--announce','--deliver','--no-deliver','--channel','--to','--best-effort-deliver','--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron rm') {
                $completions = @('--json','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron enable') {
                $completions = @('--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron disable') {
                $completions = @('--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron runs') {
                $completions = @('--id','--limit','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron run') {
                $completions = @('--due','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw cron edit') {
                $completions = @('--name','--description','--enable','--disable','--delete-after-run','--keep-after-run','--session','--agent','--clear-agent','--wake','--at','--every','--cron','--tz','--system-event','--message','--thinking','--model','--timeout-seconds','--announce','--deliver','--no-deliver','--channel','--to','--best-effort-deliver','--no-best-effort-deliver','--url','--token','--timeout','--expect-final')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw dns') {
                $completions = @('setup')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw dns setup') {
                $completions = @('--domain','--apply')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks') {
                $completions = @('list','info','check','enable','disable','install','update')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks list') {
                $completions = @('--eligible','--json','-v')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks info') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks check') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks install') {
                $completions = @('-l')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw hooks update') {
                $completions = @('--all','--dry-run')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw webhooks') {
                $completions = @('gmail')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw webhooks gmail') {
                $completions = @('setup','run')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw webhooks gmail setup') {
                $completions = @('--account','--project','--topic','--subscription','--label','--hook-url','--hook-token','--push-token','--bind','--port','--path','--include-body','--max-bytes','--renew-minutes','--tailscale','--tailscale-path','--tailscale-target','--push-endpoint','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw webhooks gmail run') {
                $completions = @('--account','--topic','--subscription','--label','--hook-url','--hook-token','--push-token','--bind','--port','--path','--include-body','--max-bytes','--renew-minutes','--tailscale','--tailscale-path','--tailscale-target')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw pairing') {
                $completions = @('list','approve')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw pairing list') {
                $completions = @('--channel','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw pairing approve') {
                $completions = @('--channel','--notify')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw plugins') {
                $completions = @('list','info','enable','disable','install','update','doctor')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw plugins list') {
                $completions = @('--json','--enabled','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw plugins info') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw plugins install') {
                $completions = @('-l')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw plugins update') {
                $completions = @('--all','--dry-run')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels') {
                $completions = @('list','status','capabilities','resolve','logs','add','remove','login','logout')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels list') {
                $completions = @('--no-usage','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels status') {
                $completions = @('--probe','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels capabilities') {
                $completions = @('--channel','--account','--target','--timeout','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels resolve') {
                $completions = @('--channel','--account','--kind','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels logs') {
                $completions = @('--channel','--lines','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels add') {
                $completions = @('--channel','--account','--name','--token','--token-file','--bot-token','--app-token','--signal-number','--cli-path','--db-path','--service','--region','--auth-dir','--http-url','--http-host','--http-port','--webhook-path','--webhook-url','--audience-type','--audience','--homeserver','--user-id','--access-token','--password','--device-name','--initial-sync-limit','--ship','--url','--code','--group-channels','--dm-allowlist','--auto-discover-channels','--no-auto-discover-channels','--use-env')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels remove') {
                $completions = @('--channel','--account','--delete')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels login') {
                $completions = @('--channel','--account','--verbose')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw channels logout') {
                $completions = @('--channel','--account')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory') {
                $completions = @('self','peers','groups')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory self') {
                $completions = @('--channel','--account','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory peers') {
                $completions = @('list')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory peers list') {
                $completions = @('--channel','--account','--json','--query','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory groups') {
                $completions = @('list','members')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory groups list') {
                $completions = @('--channel','--account','--json','--query','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw directory groups members') {
                $completions = @('--group-id','--channel','--account','--json','--limit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw security') {
                $completions = @('audit')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw security audit') {
                $completions = @('--deep','--fix','--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw skills') {
                $completions = @('list','info','check')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw skills list') {
                $completions = @('--json','--eligible','-v')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw skills info') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw skills check') {
                $completions = @('--json')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw update') {
                $completions = @('wizard','status','--json','--no-restart','--channel','--tag','--timeout','--yes')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw update wizard') {
                $completions = @('--timeout')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

            if ($commandPath -eq 'openclaw update status') {
                $completions = @('--json','--timeout')
                $completions | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
                    [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
                }
            }

}
