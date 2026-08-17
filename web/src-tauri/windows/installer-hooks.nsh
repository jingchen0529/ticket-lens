; The first release with lifecycle fixes can still be installed by an old
; client. The old client quits the desktop shell when the Windows updater
; launches NSIS, but never stops daxi.exe; so the elevated installer must
; kill leftover backends before overwriting files. Newer versions normally
; exit gracefully via the supervisor pipe; this remains the fallback for
; crashes / forced shutdowns.
;
; IMPORTANT: keep this file pure ASCII. NSIS parses scripts using the system
; ANSI codepage (CP1252 on Windows CI runners); non-ASCII text breaks the
; build or shows mojibake to customers. The Abort argument is a jump label,
; so it cannot carry a string.

!macro DAXI_STOP_LEGACY_BACKEND
  Push $0
  Push $1
  ; Pass the install dir via env var so paths with spaces never get spliced
  ; into PowerShell code.
  System::Call 'kernel32::SetEnvironmentVariable(t "DAXI_INSTALL_DIR", t "$INSTDIR") i.r0'
  StrCmp "$0" "0" daxi_stop_env_failed

  ; Match only backend/ and legacy daxi/ layouts inside this product's own
  ; install dir. Kill the whole process tree by PID, wait up to 15 seconds;
  ; if we cannot confirm it exited, abort the install instead of overwriting
  ; files behind a lock.
  nsExec::ExecToLog /TIMEOUT=30000 `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "& { $$p=@((Join-Path $$env:DAXI_INSTALL_DIR 'backend\daxi.exe'),(Join-Path $$env:DAXI_INSTALL_DIR 'daxi\daxi.exe')); $$f={@(Get-CimInstance Win32_Process -ErrorAction Stop|Where-Object {$$_.Name -ieq 'daxi.exe' -and $$_.ExecutablePath -and $$p -contains $$_.ExecutablePath})}; try {$$x=&$$f; $$x|ForEach-Object {& (Join-Path $$env:SystemRoot 'System32\taskkill.exe') /PID $$_.ProcessId /T /F|Out-Null}; $$d=(Get-Date).AddSeconds(15); while ((&$$f).Count -and (Get-Date) -lt $$d) {Start-Sleep -Milliseconds 250}; if ((&$$f).Count) {exit 2}; exit 0} catch {[Console]::Error.WriteLine($$_.Exception.Message); exit 1}}"`
  Pop $1
  ; Clear the env var in a dedicated register so the PowerShell exit code
  ; from the previous step is not overwritten.
  System::Call 'kernel32::SetEnvironmentVariable(t "DAXI_INSTALL_DIR", p 0) i.r0'
  StrCmp "$1" "0" daxi_stop_done
  Goto daxi_stop_failed

daxi_stop_env_failed:
  StrCpy $1 "env-error"
daxi_stop_failed:
  DetailPrint "Unable to stop installed backend (exit: $1)"
  ; NOTE: never add a /SD option to this MessageBox; its value is parsed as
  ; a jump label and fails with "could not resolve label".
  MessageBox MB_OK|MB_ICONSTOP "Unable to stop the installed backend service. Installation aborted. Please close Daolue and retry."
  Pop $1
  Pop $0
  Abort

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
