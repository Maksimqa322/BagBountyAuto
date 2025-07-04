#!/usr/bin/env python3
"""
Модуль разведки для BagBountyAuto
"""

import os
import sys
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor

# Добавляем путь к корневой директории проекта
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.utils.common import (
    run_command_with_activity_monitor, count_lines, setup_workspace, get_timestamp,
    print_status, print_success, print_error, time_tracker
)
from src.utils.reports_manager import get_report_path
from config.settings import TOOLS, PORTS, THREADS, KATANA_DEPTH, BLACKLIST_EXT, SENSITIVE_EXT

def check_tools():
    """Проверяет наличие необходимых инструментов"""
    time_tracker.start_stage("Проверка инструментов")
    missing_tools = []
    for tool_name, tool_cmd in TOOLS.items():
        if tool_name in ['subfinder', 'httpx', 'waybackurls', 'katana']:
            try:
                subprocess.run([tool_cmd, '--help'], capture_output=True, timeout=5)
                print_success(f"{tool_name} найден")
            except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
                print_error(f"{tool_name} не найден")
                missing_tools.append(tool_name)
    
    if missing_tools:
        print_error(f"Отсутствуют инструменты: {', '.join(missing_tools)}")
        print_error("Установите их перед запуском скрипта")
        time_tracker.end_stage("Проверка инструментов")
        return False
    
    time_tracker.end_stage("Проверка инструментов")
    return True

def main():
    parser = argparse.ArgumentParser(description='BagBountyAuto - Разведка домена')
    parser.add_argument('domain', help='Target domain (e.g. example.com)')
    parser.add_argument('--reports-dir', help='Директория для отчетов')
    parser.add_argument('--activity-timeout', type=int, default=60, help='Таймаут неактивности в секундах (по умолчанию: 60)')
    args = parser.parse_args()
    
    # Начинаем общий отсчет времени для разведки
    time_tracker.start_total()
    
    # Проверка инструментов
    if not check_tools():
        time_tracker.end_total()
        return
    
    # Настройка рабочего пространства
    time_tracker.start_stage("Настройка рабочего пространства")
    dirs = setup_workspace(args.domain)
    timestamp = get_timestamp()
    time_tracker.end_stage("Настройка рабочего пространства")
    
    print_status(f"Начало разведки для {args.domain}")
    print_status(f"Таймаут неактивности: {args.activity_timeout}с")
    
    # Этап 1: Обнаружение поддоменов
    time_tracker.start_stage("Поиск поддоменов")
    print_status("Этап 1/7: Поиск поддоменов...")
    subdomains_file = f"{dirs['subdomains']}/subdomains.txt"
    result = run_command_with_activity_monitor(
        f"{TOOLS['subfinder']} -d {args.domain} -silent", 
        subdomains_file,
        activity_timeout=args.activity_timeout
    )
    
    if not result or count_lines(subdomains_file) == 0:
        print_error("Не удалось найти поддомены. Проверьте домен и доступность subfinder.")
        time_tracker.end_stage("Поиск поддоменов")
        time_tracker.end_total()
        return
    
    time_tracker.end_stage("Поиск поддоменов")
    
    # Этап 2: Поиск живых поддоменов
    time_tracker.start_stage("Проверка живых поддоменов")
    print_status("Этап 2/7: Проверка живых поддоменов...")
    alive_file = f"{dirs['subdomains']}/alive.txt"
    result = run_command_with_activity_monitor(
        f"cat {subdomains_file} | {TOOLS['httpx']} -p {PORTS} -t {THREADS} -silent -o {alive_file}",
        activity_timeout=args.activity_timeout
    )
    
    if not result or count_lines(alive_file) == 0:
        print_error("Не найдено живых поддоменов. Проверьте доступность хостов.")
        time_tracker.end_stage("Проверка живых поддоменов")
        time_tracker.end_total()
        return
    
    time_tracker.end_stage("Проверка живых поддоменов")
    
    # Этап 3: Сбор URL с помощью waybackurls
    time_tracker.start_stage("Сбор URL (waybackurls)")
    print_status("Этап 3/7: Сбор URL (waybackurls)...")
    waybackurls_file = f"{dirs['waybackurls']}/waybackurls_urls.txt"
    run_command_with_activity_monitor(
        f"{TOOLS['waybackurls']} {args.domain}", 
        waybackurls_file,
        activity_timeout=args.activity_timeout
    )
    time_tracker.end_stage("Сбор URL (waybackurls)")
    
    # Этап 4: Сбор URL с помощью Katana
    time_tracker.start_stage("Сбор URL (katana)")
    print_status("Этап 4/7: Сбор URL (katana)...")
    katana_file = f"{dirs['katana']}/katana_urls.txt"
    run_command_with_activity_monitor(
        f"{TOOLS['katana']} -list {alive_file} -d {KATANA_DEPTH} -jc -fx -ef {BLACKLIST_EXT} -o {katana_file}",
        activity_timeout=args.activity_timeout
    )
    time_tracker.end_stage("Сбор URL (katana)")
    
    # Этап 5: Объединение и обработка URL
    time_tracker.start_stage("Обработка URL")
    print_status("Этап 5/7: Обработка URL...")
    all_urls_file = f"{dirs['urls']}/all_urls.txt"
    
    # Объединение результатов только если файлы существуют и не пустые
    waybackurls_exists = os.path.exists(waybackurls_file) and os.path.getsize(waybackurls_file) > 0
    katana_exists = os.path.exists(katana_file) and os.path.getsize(katana_file) > 0
    
    if waybackurls_exists and katana_exists:
        run_command_with_activity_monitor(
            f"cat {waybackurls_file} {katana_file} | sort -u > {all_urls_file}",
            activity_timeout=args.activity_timeout
        )
    elif waybackurls_exists:
        run_command_with_activity_monitor(
            f"cp {waybackurls_file} {all_urls_file}",
            activity_timeout=args.activity_timeout
        )
    elif katana_exists:
        run_command_with_activity_monitor(
            f"cp {katana_file} {all_urls_file}",
            activity_timeout=args.activity_timeout
        )
    else:
        print_error("Не удалось собрать URL. Создаем пустой файл.")
        open(all_urls_file, 'w').close()
    
    # Поиск чувствительных файлов
    if os.path.exists(all_urls_file) and os.path.getsize(all_urls_file) > 0:
        sensitive_files = f"{dirs['urls']}/sensitive_files.txt"
        run_command_with_activity_monitor(
            f"grep -aE '{SENSITIVE_EXT}' {all_urls_file} > {sensitive_files}",
            activity_timeout=args.activity_timeout
        )
        
        # Поиск URL с параметрами
        param_file = f"{dirs['urls']}/param_urls.txt"
        run_command_with_activity_monitor(
            f"grep -aF '=' {all_urls_file} | {TOOLS['sed']} 's/=.*/=/' | sort -u > {param_file}",
            activity_timeout=args.activity_timeout
        )
        
        # Специфичные категории URL
        for ext, name in [("js$", "js_files.txt"), ("php$", "php_files.txt"), ("/api/", "api_endpoints.txt")]:
            run_command_with_activity_monitor(
                f"grep -a '{ext}' {all_urls_file} > {dirs['urls']}/{name}",
                activity_timeout=args.activity_timeout
            )
    else:
        print_error("Файл all_urls.txt пуст или не существует, пропускаем обработку URL")
        # Создаем пустые файлы
        for name in ["sensitive_files.txt", "param_urls.txt", "js_files.txt", "php_files.txt", "api_endpoints.txt"]:
            open(f"{dirs['urls']}/{name}", 'w').close()
    
    time_tracker.end_stage("Обработка URL")
    
    # Этап 6: Скачивание файлов
    time_tracker.start_stage("Скачивание файлов")
    print_status("Этап 6/7: Скачивание файлов...")
    
    def download_files(file_type, urls_file, output_dir):
        if os.path.exists(urls_file) and os.path.getsize(urls_file) > 0:
            print_status(f"Скачивание {file_type} файлов...")
            # Добавляем дополнительные параметры для лучшей обработки ошибок
            run_command_with_activity_monitor(
                f"{TOOLS['wget']} -q -i {urls_file} -P {output_dir} --timeout=10 --tries=1 --no-check-certificate --no-verbose --continue --restrict-file-names=windows",
                activity_timeout=args.activity_timeout
            )
        else:
            print_error(f"Файл {urls_file} пуст или не существует, пропускаем скачивание {file_type} файлов")
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(download_files, "sensitive", f"{dirs['urls']}/sensitive_files.txt", dirs['sensitive'])
        executor.submit(download_files, "js", f"{dirs['urls']}/js_files.txt", dirs['js'])
        executor.submit(download_files, "php", f"{dirs['urls']}/php_files.txt", dirs['php'])
    
    time_tracker.end_stage("Скачивание файлов")
    
    # Этап 7: Генерация отчетов
    time_tracker.start_stage("Генерация отчетов")
    print_status("Этап 7/7: Генерация отчетов...")
    report_filename = f"recon_report_{timestamp}.md"
    report_file = get_report_path('recon', args.domain, report_filename, args.reports_dir)
    
    with open(report_file, 'w', encoding='utf-8') as report:
        report.write(f"# Отчет разведки: {args.domain}\n")
        report.write(f"**Дата:** {timestamp}\n\n")
        
        # Статистика
        stats = {
            "Поддомены": f"{dirs['subdomains']}/subdomains.txt",
            "Живые поддомены": f"{dirs['subdomains']}/alive.txt",
            "Всего URL": f"{dirs['urls']}/all_urls.txt",
            "Чувствительные файлы": f"{dirs['urls']}/sensitive_files.txt",
            "URL с параметрами": f"{dirs['urls']}/param_urls.txt"
        }
        
        report.write("## Статистика\n")
        for name, file in stats.items():
            count = count_lines(file)
            report.write(f"- **{name}:** {count}\n")
        
        # Директории
        report.write("\n## Структура проекта\n")
        for dir_name, dir_path in dirs.items():
            report.write(f"- `{dir_path}`\n")
    
    time_tracker.end_stage("Генерация отчетов")
    
    print_success(f"Завершено! Отчет: {report_file}")
    
    # Финальная статистика
    subdomains_count = count_lines(f"{dirs['subdomains']}/subdomains.txt")
    alive_count = count_lines(f"{dirs['subdomains']}/alive.txt")
    urls_count = count_lines(f"{dirs['urls']}/all_urls.txt")
    
    print_status("Всего собрано данных:")
    print(f"  Поддомены: {subdomains_count}")
    print(f"  Живые хосты: {alive_count}")
    print(f"  URL: {urls_count}")
    
    # Показываем статистику времени выполнения
    time_tracker.print_summary()
    
    # Завершаем общий отсчет времени
    time_tracker.end_total()

if __name__ == "__main__":
    main()
