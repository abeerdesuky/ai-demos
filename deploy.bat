@echo off
chcp 65001 >nul
cd /d "%~dp0"
where git >nul 2>nul || (echo git is not installed: https://git-scm.com/downloads & pause & exit /b 1)
if not exist .git git init -q
git add -A
git commit -qm "AI website + chatbot demos"
git branch -M main
where gh >nul 2>nul && gh auth status >nul 2>nul && (gh repo create ai-demos --public --source . --push & goto done)
set /p URL=Create an empty repo at github.com/new named ai-demos and paste its URL: 
git remote remove origin 2>nul
git remote add origin %URL%
git push -u origin main
:done
echo Done! Now go to https://dashboard.render.com/blueprints and create a New Blueprint from this repo.
pause
