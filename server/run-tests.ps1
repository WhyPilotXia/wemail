$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -m unittest discover -s tests -v
