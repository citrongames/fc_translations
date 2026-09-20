KATTE NI SHIROKUMA / FAMICOM
РУССКИЙ ПЕРЕВОД — FINAL v1.0
============================================================

СТАТУС
------
Проект завершён.

Финальная сборка прошла полное практическое прохождение игры от начала
до финальных титров. После последнего QA были отдельно подтверждены:
  - все 27 динамических имён врагов в бою;
  - финальные титры полностью на русском;
  - оригинальное зацикливание титров и музыки после последней страницы;
  - отсутствие зависания на К.СИМАНО;
  - сохранение расширенного текстового runtime после исправления концовки.

Финальная ROM является байт-в-байт той же проверенной сборкой v0.25,
переименованной в релиз v1.0. Игровые данные после теста не менялись.

ФИНАЛЬНЫЙ ROM
-------------
  Katte_Shirokuma_RU_FINAL_v1.0.nes

  Size:    393232 bytes
  SHA-256: 75005f885f4d040dcc1a0e0b521ef12eb5d466815735ebe75a18c17fa33db16b
  SHA-1:   7046af1b8e51dadb0b97ecb9f54aaf0e320ecb2a
  MD5:     120bea9924d0613ab64cb052619df0cb
  CRC32:   138A277B

iNES:
  Mapper: 1 / MMC1
  PRG:    256 KiB (16 x 16 KiB)
  CHR:    128 KiB (16 x 8 KiB)

Исходная японская ROM для старых extraction/repack-инструментов:
  Famicom Doubutsu Seitai Zukan! - Katte ni Shirokuma -
  Mori o Sukue no Maki! (Japan)
  PRG: 128 KiB, CHR: 128 KiB
  CRC32 данных без 16-байтного iNES header: F8C1A690
  SHA-256 исходной ROM, использовавшейся при разработке:
  13944719c67734201870db74f829f1e7c7bb867461ee83f2176b2afa2507ddd8

ВАЖНО: финальный русский ROM расширен до 256 KiB PRG. Поэтому инструменты
для FINAL и инструменты для исходной японской ROM разделены.

БЫСТРАЯ ПРОВЕРКА FINAL
----------------------
Требуется Python 3.

  python tools/validate_final.py Katte_Shirokuma_RU_FINAL_v1.0.nes     --script script/script_ru_final.txt

Ожидается PASS и SHA-256, указанный выше.

ИЗВЛЕЧЕНИЕ ТЕКСТА
-----------------
Из FINAL:

  python tools/extract_text.py Katte_Shirokuma_RU_FINAL_v1.0.nes     -o my_script.txt

Из исходной японской ROM:

  python tools/extract_text.py "original.nes" -o script_jp.txt --mode jp

Скрипт содержит 1142 записи:
  B0 = 153 коротких меток/имён/предметов;
  B1 = 898 основных сценарных строк;
  D  = 91 словарную/общую строку.

ВСТАВКА ТЕКСТА В FINAL
----------------------
Редактируй script/script_ru_final.txt или результат extract_text.py.
Не удаляй @@-заголовки и @@END. Перенос строки внутри окна — {LN},
следующая страница — {NEXT}.

  python tools/insert_text.py Katte_Shirokuma_RU_FINAL_v1.0.nes     my_script.txt -o Katte_Shirokuma_RU_EDITED.nes

Inserter заново упаковывает B0/D и расширенные B1-банки, обновляя указатели.
На неизменённом финальном сценарии результат БАЙТ-ИДЕНТИЧЕН FINAL ROM.

Для экспериментов непосредственно с исходной 128 KiB японской ROM оставлен
tools/repack_original.py. Это старый локальный repacker; для уже расширенной
FINAL ROM используй только insert_text.py.

ИМЕНА ВРАГОВ
------------
Отдельная динамическая таблица боя не входит в B0/B1/D.
В FINAL в ней 27 имён.

Извлечение:
  python tools/enemy_names.py extract Katte_Shirokuma_RU_FINAL_v1.0.nes     -o enemy_names.tsv

Вставка:
  python tools/enemy_names.py insert Katte_Shirokuma_RU_FINAL_v1.0.nes     enemy_names.tsv -o edited.nes

Актуальная таблица лежит в script/enemy_names_final.tsv.

ФИНАЛЬНЫЕ ТИТРЫ
---------------
131-байтовый staff-roll хранится отдельно от основного сценария.

Извлечение:
  python tools/credits_tool.py extract Katte_Shirokuma_RU_FINAL_v1.0.nes     -o credits.txt

Вставка:
  python tools/credits_tool.py insert Katte_Shirokuma_RU_FINAL_v1.0.nes     credits.txt -o edited.nes

Текущий текст: script/credits_final.txt.

ГРАФИКА / CHR
-------------
Для PNG-инструментов требуется Pillow:

  python -m pip install -r tools/requirements.txt

Извлечь один 8 KiB CHR-банк:
  python tools/extract_chr.py Katte_Shirokuma_RU_FINAL_v1.0.nes     --bank 2 -o chr_dump

Извлечь все 16 банков — просто не указывать --bank.

Вернуть PNG ровно одного 8 KiB банка:
  python tools/insert_chr.py Katte_Shirokuma_RU_FINAL_v1.0.nes     chr_dump/chr_bank_02.png --bank 2 -o edited.nes

PNG использует четыре уровня яркости 0/85/170/255, соответствующие NES 2bpp
индексам 0..3. Round-trip extract -> insert проверен байт-в-байт.

assets/chr_bank_02_final.png — прямой дамп одного из финальных CHR-банков.
assets/user_font_sheet_latest.png — рабочая визуальная таблица шрифта проекта.

ПРОХОЖДЕНИЕ
-----------
WALKTHROUGH_RU.txt — полный маршрут, использовавшийся во время QA.
В финальном пакете заголовок и финальные проверки обновлены для v1.0.

СТРУКТУРА ПАКЕТА
----------------
Katte_Shirokuma_RU_FINAL_v1.0.nes   финальная игра
README_RU.txt                       этот файл
WALKTHROUGH_RU.txt                  полное прохождение + QA-маршрут
FINAL_TEST_STATUS.txt               что подтверждено финальным тестом
CHANGELOG.txt                       краткая история важных исправлений
CHECKSUMS.txt                       контрольные суммы файлов

script/
  script_ru_final.txt               полный русский B0/B1/D сценарий
  script_jp_reference.txt           исходный японский дамп для справки
  glossary_ru.md                    терминология проекта
  enemy_names_final.tsv             все 27 динамических имён врагов
  credits_final.txt                 семь страниц финальных титров

assets/
  user_font_sheet_latest.png        визуальная таблица текущего шрифта
  chr_bank_02_final.png             CHR-банк в формате tools/extract_chr.py

 tools/
  katte_codec.py                    кодировка/таблицы блоков
  extract_text.py                   JP/FINAL extraction
  insert_text.py                    repack текста FINAL
  enemy_names.py                    27 боевых имён
  credits_tool.py                   staff-roll
  extract_chr.py / insert_chr.py    NES CHR <-> PNG
  validate_final.py                 финальный структурный validator
  repack_original.py                repack исходной 128 KiB ROM
  layout_check.py                   старый layout helper для original repack
  roundtrip_original.py             исходный round-trip test
  requirements.txt                  Pillow для PNG-инструментов
  selftest_final.py                 полный no-op round-trip self-test

 docs/
  TECHNICAL_NOTES.txt
  TEXT_FORMAT.txt
  CHR_LAYOUT.txt
  RUSSIAN_FONT_MAP.txt
  TOOLS_RU.txt

source/
  FINAL_DELTA_NOTES.txt             последние технические исправления

ОГРАНИЧЕНИЯ ТЕКСТА
------------------
Основное окно: 16 знакомест x 3 строки на страницу.
Короткие B0-метки FINAL собраны с лимитом 6 клеток.

Особые байты B1 нельзя удалять только потому, что они «не видны»:
  $0D = -5 ОЗ + словарный текст
  $1E = восстановление/пересчёт ОЗ + словарный текст
  $47 = +25 УМ + словарный текст
  $11/$45 = динамические имена/говорящий
  $5B-$5F = динамика боя в боевых строках
  $53/$55, $60-$88, $8A, $B8 и др. = служебные эффекты.

Если правишь сценарий вручную — сохраняй такие {XX} токены.

FINAL
-----
Игра полностью пройдена. v1.0 считается релизной сборкой.

Полный self-test пакета:
  python tools/selftest_final.py

Последний успешный вывод сохранён в SELFTEST_LOG.txt.
