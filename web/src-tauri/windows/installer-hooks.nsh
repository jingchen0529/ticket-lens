; 首个带生命周期修复的版本仍可能由旧客户端发起更新。旧客户端在 Windows
; updater 启动 NSIS 时会直接退出桌面壳，却不会结束 daxi.exe；因此必须由已
; 提权的安装器在覆盖文件前清掉遗留后端。后续版本通常会先走监督管道优雅退出，
; 此处继续作为崩溃/强制关机后的兜底。

!macro DAXI_STOP_LEGACY_BACKEND
  Push $0
  Push $1
  ; 通过环境变量传递安装目录，避免把含空格的路径直接拼进 PowerShell 代码。
  System::Call 'kernel32::SetEnvironmentVariable(t "DAXI_INSTALL_DIR", t "$INSTDIR") i.r0'
  StrCmp "$0" "0" daxi_stop_env_failed

  ; 只匹配本产品安装目录内的新 backend/ 与历史 daxi/ 布局。按 PID 结束整棵
  ; 进程树，最长等待 15 秒；不能确认已退出时宁可中止安装，也不带锁覆盖文件。
  nsExec::ExecToLog /TIMEOUT=30000 `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& { $$p=@((Join-Path $$env:DAXI_INSTALL_DIR 'backend\daxi.exe'),(Join-Path $$env:DAXI_INSTALL_DIR 'daxi\daxi.exe')); $$f={@(Get-CimInstance Win32_Process -ErrorAction Stop|Where-Object {$$_.Name -ieq 'daxi.exe' -and $$_.ExecutablePath -and $$p -contains $$_.ExecutablePath})}; try {$$x=&$$f; $$x|ForEach-Object {& (Join-Path $$env:SystemRoot 'System32\taskkill.exe') /PID $$_.ProcessId /T /F|Out-Null}; $$d=(Get-Date).AddSeconds(15); while ((&$$f).Count -and (Get-Date) -lt $$d) {Start-Sleep -Milliseconds 250}; if ((&$$f).Count) {exit 2}; exit 0} catch {[Console]::Error.WriteLine($$_.Exception.Message); exit 1}}"`
  Pop $1
  ; 清理环境变量使用独立寄存器，不能覆盖上一步 PowerShell 的退出码。
  System::Call 'kernel32::SetEnvironmentVariable(t "DAXI_INSTALL_DIR", p 0) i.r0'
  StrCmp "$1" "0" daxi_stop_done
  Goto daxi_stop_failed

daxi_stop_env_failed:
  StrCpy $1 "env-error"
daxi_stop_failed:
  DetailPrint "Unable to stop installed backend (exit: $1)"
  MessageBox MB_OK|MB_ICONSTOP /SD IDOK "无法停止旧版后台服务，安装已中止。请关闭 Daolue 后重试。"
  Pop $1
  Pop $0
  Abort "旧版后台服务仍在运行"

daxi_stop_done:
  Pop $1
  Pop $0
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro DAXI_STOP_LEGACY_BACKEND
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro DAXI_STOP_LEGACY_BACKEND
!macroend
