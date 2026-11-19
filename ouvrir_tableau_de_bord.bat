@echo off
rem Ouvre le tableau de bord dans le navigateur. Double-cliquer sur ce fichier.
rem Fermer cette fenetre noire arrete le tableau de bord.
cd /d "%~dp0"
rem Environnement Python : d'abord .venv dans le dossier du projet, sinon celui du dossier personnel.
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%USERPROFILE%\.venvs\financial-market-dashboard\Scripts\python.exe"
if not exist "%PYTHON%" goto :sans_python

echo Demarrage du tableau de bord...
echo La page s'ouvre dans le navigateur dans quelques secondes : http://127.0.0.1:8510
echo Pour l'arreter : fermer cette fenetre.
rem Le navigateur est ouvert apres 6 secondes, le temps que la page demarre.
if not defined TABLEAU_SANS_NAVIGATEUR start "" /min cmd /c "ping -n 7 127.0.0.1 >nul & start http://127.0.0.1:8510"
"%PYTHON%" -m streamlit run tableau_de_bord.py --server.headless true --server.port 8510
pause
goto :eof

:sans_python
echo Environnement Python introuvable : %PYTHON%
echo Voir la section "Installer et lancer" du README.
pause
