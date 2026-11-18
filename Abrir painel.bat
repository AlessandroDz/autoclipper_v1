@echo off
rem Abre o painel do Auto-Clipper no navegador.
rem Feche esta janela para desligar o Auto-Clipper.
cd /d "%~dp0"
title Auto-Clipper
".venv\Scripts\python.exe" -m autoclipper.painel
