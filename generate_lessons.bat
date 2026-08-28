@echo off
REM ═══════════════════════════════════════════════
REM Автогенерация занятий на следующую неделю
REM Запускается Планировщиком задач Windows
REM ═══════════════════════════════════════════════

cd /d C:\attendance_tracker
call venv\Scripts\activate.bat
python manage.py generate_lessons --days 7 >> logs\generate_lessons.log 2>&1
echo [%date% %time%] Занятия сгенерированы >> logs\generate_lessons.log