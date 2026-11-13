param([Parameter(Mandatory=$true)][string]$ExpectedInstance)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
$proofPath = Join-Path $repoPath 'evidence/standalone-install.json'
$proof = Get-Content -LiteralPath $proofPath -Raw -Encoding UTF8 | ConvertFrom-Json
$observed = Invoke-RestMethod -Uri 'http://127.0.0.1:5198/healthz' -TimeoutSec 3
if ($observed.instanceId -ne $ExpectedInstance -or $observed.instanceId -ne $proof.demoService.instanceId -or $observed.pid -ne $proof.demoService.pid -or $observed.projectId -ne 'super-ledger-demo') { throw 'Service identity changed; preserve the process' }
$serviceProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$observed.pid)
if ($null -eq $serviceProcess -or $serviceProcess.CommandLine -notlike '*-m super_ledger*' -or $serviceProcess.CommandLine -notlike '*build\demo-project*') { throw 'Service command differs; preserve the process' }
$packageFolder = Split-Path -Parent $proof.packageImportedFrom
$siteFolder = Split-Path -Parent $packageFolder
$envFolder = Split-Path -Parent (Split-Path -Parent $siteFolder)
$pythonPath = Join-Path $envFolder 'Scripts/python.exe'
$proofFolder = Split-Path -Parent $envFolder
$resolvedPython = [IO.Path]::GetFullPath($pythonPath)
if (-not $resolvedPython.StartsWith(([IO.Path]::GetFullPath((Join-Path $repoPath 'build/'))),[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $resolvedPython)) { throw 'Unexpected owned environment path' }
Stop-Process -Id ([int]$observed.pid)
$demoPath = Join-Path $repoPath 'build/demo-project'
$serverArguments = '-I -m super_ledger --project "' + $demoPath + '" serve --port 5198'
Start-Process -FilePath $resolvedPython -ArgumentList $serverArguments -WindowStyle Hidden -WorkingDirectory $proofFolder -RedirectStandardOutput (Join-Path $proofFolder 'server.stdout.log') -RedirectStandardError (Join-Path $proofFolder 'server.stderr.log')
Write-Output 'Restarted the verified owned demo; recheck HTTP against its new stdout identity.'
