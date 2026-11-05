#!/usr/bin/env bash
# رفع الريبو على GitHub (ماك / لينكس / Git Bash على ويندوز)
set -e
cd "$(dirname "$0")"
command -v git >/dev/null || { echo "❌ git مش متسطّب: https://git-scm.com/downloads"; exit 1; }
[ -d .git ] || git init -q
git add -A
git commit -qm "AI website + chatbot demos" || true
git branch -M main
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh repo create ai-demos --public --source . --push
else
  read -rp "اعمل ريبو فاضي على github.com/new باسم ai-demos والصق اللينك هنا: " URL
  git remote remove origin 2>/dev/null || true
  git remote add origin "$URL"
  git push -u origin main
fi
echo "✅ اترفع! روح على https://dashboard.render.com/blueprints واعمل New Blueprint من الريبو ده."
