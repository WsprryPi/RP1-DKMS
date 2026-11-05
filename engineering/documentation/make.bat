@ECHO OFF
REM SPDX-License-Identifier: MIT
REM Adapted from WsprryPi-Docs; copyright 2024 Lee Bussy.
SETLOCAL
PUSHD "%~dp0"
IF "%SPHINXBUILD%" == "" SET "SPHINXBUILD=python -m sphinx"
IF "%BUILDDIR%" == "" SET "BUILDDIR=%TEMP%\rp1-gpclk-dkms-docs"
IF "%1" == "" (
    %SPHINXBUILD% -M help "..\..\docs" "%BUILDDIR%" %SPHINXOPTS%
) ELSE (
    %SPHINXBUILD% -M "%~1" "..\..\docs" "%BUILDDIR%" %SPHINXOPTS%
)
SET "BUILD_EXIT=%ERRORLEVEL%"
POPD
EXIT /B %BUILD_EXIT%
