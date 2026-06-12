# Лабораторная работа №4 — Архитектура компьютера

**Студент:** Новиков Даниил Дмитриевич  
**Группа:** P3231  
**Проверил:** Пенской Александр Владимирович  
**Вариант:** `lisp | stack | harv | mc | tick | binary | stream | port | pstr | prob1`

## Язык программирования

Разработанный язык имеет Lisp-подобный синтаксис: программа состоит из S-expression, то есть выражений в скобочной префиксной форме. Любая конструкция языка является выражением и оставляет результат вычисления на стеке. Если результат верхнеуровневого выражения не нужен, транслятор после него генерирует `DROP`.

### Синтаксис

Ниже приведено описание синтаксиса в форме, близкой к БНФ.

```ebnf
program          ::= expression*

expression       ::= integer
                   | symbol
                   | string_literal
                   | list_expression

list_expression  ::= "(" form ")"

form             ::= form_setq
                   | form_if
                   | form_loop
                   | form_begin
                   | form_proc
                   | form_call
                   | form_arithmetic
                   | form_comparison
                   | form_io
                   | form_memory
                   | form_pstr

integer          ::= ["-"] digit+
symbol           ::= symbol_char+
string_literal   ::= '"' string_char* '"'

form_setq        ::= "setq" symbol expression
form_if          ::= "if" expression expression expression
form_loop        ::= "loop" expression expression*
form_begin       ::= "begin" expression*

form_proc        ::= "proc" symbol parameter_list? expression*
parameter_list   ::= "(" symbol* ")"
form_call        ::= "call" symbol expression*

form_arithmetic  ::= ("+" | "-" | "*" | "/" | "%") expression expression+
form_comparison  ::= ("=" | "!=" | "<" | ">" | "<=" | ">=") expression expression

form_io          ::= "read-char"
                   | "read-int"
                   | "print-char" expression
                   | "print-int" expression
                   | "print" expression
                   | "print-pstr" expression

form_memory      ::= "load-at" expression
                   | "store-at" expression expression

form_pstr        ::= "pstr-len" expression
                   | "pstr-get" expression expression
                   | "pstr-set" expression expression expression
```

Комментарии начинаются с символа `;` и продолжаются до конца строки.

### Семантика

Стратегия вычислений — строгая, с вычислением аргументов слева направо. Например выражение:

```lisp
(+ (* 2 3) x)
```

вычисляется так:

1. вычисляется `(* 2 3)`;
2. загружается значение `x`;
3. выполняется сложение двух верхних значений стека.

Все конструкции языка являются выражениями:

| Конструкция | Результат |
|---|---|
| `(setq x expr)` | значение `expr` |
| `(if cond then else)` | значение выбранной ветки |
| `(loop cond body...)` | `0` после завершения цикла |
| `(begin e1 ... en)` | значение последнего выражения или `0`, если тело пустое |
| `(call f args...)` | значение, возвращённое процедурой |
| `(print s)` / `(print-pstr s)` | `0` |
| `(print-char x)` / `(print-int x)` | напечатанное значение |
| `(load-at addr)` | слово из памяти данных по адресу `addr` |
| `(store-at addr value)` | `0` |
| `(pstr-len s)` | длина строки |
| `(pstr-get s i)` | код символа строки по индексу `i` |
| `(pstr-set s i value)` | `0` |

### Области видимости

Переменные размещаются в памяти данных. Каждой переменной транслятор сопоставляет байтовый адрес машинного слова в `Data Memory`.

Области видимости:

- глобальные переменные доступны из основной программы и процедур;
- параметры процедуры образуют локальную область видимости для тела процедуры;
- если имя найдено в локальной области параметров, используется адрес параметра;
- если локального имени нет, используется глобальная переменная.

Параметры процедур физически также размещаются в памяти данных. При вызове процедуры транслятор сохраняет старые значения параметров, записывает новые аргументы, выполняет `CALL`, после возврата восстанавливает старые значения параметров и возвращает результат процедуры. За счёт этого поддерживаются рекурсивные вызовы.

Пример рекурсивной процедуры:

```lisp
(proc fact (n)
  (if (= n 0)
      1
      (* n (call fact (- n 1)))))

(print-int (call fact 5))
```

Результат выполнения:

```text
120
```

### Типизация и литералы

Язык имеет простую динамическую модель значений. Основное значение времени исполнения — 32-битное машинное слово со знаковой интерпретацией.

Используются следующие виды литералов:

| Вид литерала | Пример | Представление                             |
|---|---|-------------------------------------------|
| Целое число | `13`, `-5` | непосредственный операнд команды `PUSHI`  |
| Строка | `"hello"` | статическая Pascal-строка в памяти данных |
| Символ | `x`, `fact` | имя переменной, процедуры                 |

Логические значения представлены числами:

- `0` — ложь;
- любое ненулевое значение — истина;
- операции сравнения возвращают `0` или `1`.

Строка не является отдельным объектом Python-модели во время исполнения. Строковый литерал транслируется в адрес Pascal-строки в памяти данных. Программа работает со строкой через обычные машинные инструкции чтения/записи памяти.

---

## Организация памяти

Процессор имеет Гарвардскую архитектуру: память команд и память данных разделены. Также отдельно существует память микропрограмм.

### Основные параметры

| Параметр | Значение          |
|---|-------------------|
| Размер машинного слова данных | 32 бита / 4 байта |
| Размер инструкции | 32 бита / 4 байта |
| Адресация | байтовая          |
| Порядок байт инструкции | big-endian        |
| Порядок байт данных | little-endian     |
| Тип памяти данных | однопортовая      |
| Архитектура | Гарвардская       |
| Система команд | стековая          |
| Управление | микропрограммное  |
| Ввод-вывод | port-mapped I/O   |

Адреса инструкций и данных являются байтовыми. Так как инструкция занимает 4 байта, адреса инструкций имеют вид `0`, `4`, `8`, `12`, ... . Данные также хранятся машинными словами по 4 байта, поэтому адреса переменных и элементов строк кратны 4.

### Виды памяти

```text
          Instruction Memory
+----------------------------------+
| 0000 : JMP program_start         |
| 0004 : code of procedure 1       |
| 0008 : code of procedure 1       |
| ...                              |
| N    : program_start             |
| ...                              |
|      : main program              |
| ...                              |
|      : HALT                      |
+----------------------------------+
```

```text
             Data Memory
+----------------------------------+
| 0000 : variable / pstr word      |
| 0004 : variable / pstr word      |
| 0008 : variable / pstr word      |
| ...                              |
| addr : length of pstr            |
| addr+4 : char 0                  |
| addr+8 : char 1                  |
| ...                              |
| 1000 : dynamic array cell        |
| 1004 : dynamic array cell        |
| ...                              |
+----------------------------------+
```

```text
          Microprogram Memory
+----------------------------------+
| 000 : FETCH microinstruction     |
| 001 : HALT microinstruction      |
| 002 : PUSHI microinstruction     |
| ...                              |
|     : LOAD/1                     |
|     : LOAD/2                     |
|     : STORE/1                    |
|     : STORE/2                    |
| ...                              |
+----------------------------------+
```

### Регистры процессора

Регистры являются внутренними регистрами процессора и не доступны программисту напрямую. Программист работает со стеком, переменными, процедурами и памятью через конструкции языка.

Назначение регистров:

| Регистр | Назначение |
|---|---|
| `PC` | байтовый адрес текущей инструкции в памяти команд |
| `IR` | текущая инструкция |
| `mPC` | адрес текущей микроинструкции в памяти микропрограмм |
| `SP` | байтовый адрес вершины стека данных |
| `T` | кэш верхушки стека данных, `T = Stack[SP]` |
| `F` | временный регистр для второго операнда АЛУ |
| `AR` | адрес текущего обращения к памяти данных |
| `R` | байтовый указатель вершины стека возвратов |
| `NZ` | флаги результата АЛУ |

Важно: наличие `T`, `F`, `AR`, `R` не делает ISA регистровой. Это внутренние микрорегистры datapath. В системе команд нет инструкций, которые позволяют программисту явно обращаться к этим регистрам.

### Что доступно программисту

Программисту доступны:

- стековая модель вычислений через выражения;
- переменные языка;
- процедуры;
- статические строки;
- чтение и запись памяти через `load-at` и `store-at`;
- ввод-вывод через `read-char`, `read-int`, `print-char`, `print-int`, `print`.

Программисту недоступны напрямую:

- `PC`, `IR`, `mPC`;
- `SP`, `T`, `F`, `AR`, `R`;
- память микропрограмм;
- прямое изменение памяти команд.

### Размещение инструкций и процедур

Транслятор разделяет верхнеуровневые выражения на определения процедур и основную программу. В начало памяти команд помещается переход через код процедур к началу основной программы.

Схема размещения:

```text
Instruction Memory
+----------------------------------+
| 0000 : JMP main_start            |
| 0004 : procedure code            |
| ...                              |
| main_start : main expression 1   |
| ...                              |
|          : HALT                  |
+----------------------------------+
```

Процедуры хранятся в памяти команд. Вызов процедуры выполняется командой `CALL address`, где `address` — адрес первой инструкции процедуры. Возврат выполняется командой `RET`. Адрес возврата хранится в `Return Stack`.

### Статические и динамические данные

Статические данные создаются транслятором до начала исполнения программы:

- строковые литералы;
- ячейки переменных;
- ячейки параметров процедур;
- служебные временные ячейки транслятора.

Динамические данные могут размещаться программой вручную через адреса. Например, массив можно разместить с адреса `1000`:

```lisp
(setq ARR_BASE 1000)
(setq WORD_SIZE 4)
(store-at (+ ARR_BASE (* i WORD_SIZE)) value)
```

В этом случае транслятор не выделяет массив как отдельный объект: программа сама вычисляет адреса элементов и обращается к памяти через `load-at` и `store-at`.

### Литералы, константы, переменные, инструкции, процедуры

#### Целочисленные литералы

Целочисленный литерал используется через непосредственную адресацию, если он помещается в signed 24-bit operand команды `PUSHI`.

Пример:

```lisp
(print-int 13)
```

транслируется в стековую последовательность вида:

```text
PUSHI 13
DUP
OUT 2
DROP
```

#### Строковые литералы

Строковый литерал сохраняется в статическую область памяти данных в формате Pascal string.

Например строка:

```lisp
"abc"
```

размещается так:

```text
addr + 0  : 3    ; length
addr + 4  : 97   ; 'a'
addr + 8  : 98   ; 'b'
addr + 12 : 99   ; 'c'
```

Один символ занимает одно машинное слово. Если строковых литералов несколько, они размещаются в памяти данных последовательно, друг за другом.

#### Переменные

Переменная отображается на ячейку памяти данных. Переменные не отображаются на пользовательские регистры, потому что ISA стековая. Если переменных много, транслятор просто выделяет больше слов в памяти данных.

Пример:

```lisp
(setq x 13)
```

транслируется примерно так:

```text
PUSHI 13
DUP
STORE addr(x)
```

Команда `DUP` нужна, чтобы `setq` оставалась выражением и возвращала присваиваемое значение.

#### Процедуры

Процедуры размещаются в памяти команд перед основной программой. Адреса вызовов сначала могут быть неизвестны, поэтому транслятор использует patching: сначала создаёт инструкцию `CALL 0`, а после компиляции процедур подставляет правильный байтовый адрес процедуры.

Параметры процедур размещаются в памяти данных. Перед вызовом старые значения параметров сохраняются на стеке, затем записываются новые аргументы. После возврата результат временно сохраняется, старые параметры восстанавливаются, а результат снова загружается на стек.
    

### Отображение сложных выражений на стек, регистры и память

Пример выражения:

```lisp
(+ (* 2 3) x)
```

транслируется в стековый код:

```text
PUSHI 2
PUSHI 3
MUL
LOAD addr(x)
ADD
```

Пошагово:

```text
PUSHI 2:
Stack = [2]
T = 2

PUSHI 3:
Stack = [2, 3]
T = 3

MUL:
F = T = 3
T = Stack[SP - 4] = 2
SP = SP - 4
ALU = T * F = 6
Stack[SP] = 6
T = 6

LOAD x:
AR = addr(x)
Stack.push(DataMemory[AR])
T = value(x)

ADD:
F = T = value(x)
T = 6
ALU = 6 + value(x)
Stack[SP] = result
T = result
```

Таким образом, промежуточные значения сложных выражений находятся на стеке данных, верхушка стека кэшируется в `T`, второй операнд бинарной операции временно переносится в `F`, адрес обращения к памяти защёлкивается в `AR`.

---

## Система команд

Процессор является стековой машиной с микропрограммным управлением. Операции арифметики, сравнения, переходов, вызова процедур и ввода-вывода реализуются командами ISA, которые во время исполнения раскладываются на микроинструкции.

### Типы данных

Основной тип данных — 32-битное машинное слово. Арифметика выполняется над знаковыми 32-битными значениями. Логические значения представлены числами `0` и `1`.

Строки представлены адресами Pascal-строк в памяти данных.

### Кодирование инструкций

Каждая инструкция занимает 4 байта:

```text
31          24 23                         0
+-------------+----------------------------+
| opcode      | operand                    |
| 8 bit       | 24 bit                     |
+-------------+----------------------------+
```

- `opcode` — код операции;
- `operand` — непосредственное значение, адрес команды, адрес памяти или номер порта;
- для `PUSHI` operand интерпретируется как signed 24-bit;
- для адресных команд operand интерпретируется как unsigned 24-bit;
- инструкции без операнда требуют `operand = 0`.

### Порты ввода-вывода

| Порт | Назначение |
|---:|---|
| `0` | входной поток символов |
| `1` | выходной поток символов |
| `2` | выходной поток десятичного представления целого числа |

Ввод-вывод реализован специальными инструкциями `IN port` и `OUT port`.

При старте модели входной текст превращается в буфер символов:

```text
"hello" -> ['h', 'e', 'l', 'l', 'o']
```

Команда `IN 0` забирает один символ из входного буфера. Если буфер пуст, моделирование останавливается с причиной `Input stream exhausted`. Команда `OUT 1` добавляет один символ в выходной буфер. Команда `OUT 2` добавляет десятичную строковую запись целого числа.

### Набор инструкций

Количество тактов указано для полного цикла исполнения команды, включая такт `FETCH`.

| Opcode | Операнд | Тактов | Семантика |
|---|---:|---:|---|
| `HALT` | нет | 2 | остановить моделирование |
| `PUSHI` | signed imm24 | 2 | `push(operand)` |
| `DROP` | нет | 2 | удалить верхушку стека |
| `DUP` | нет | 2 | продублировать верхушку стека |
| `LOAD` | data address | 3 | `push(DataMemory[operand])` |
| `STORE` | data address | 3 | `DataMemory[operand] = pop()` |
| `LOADI` | нет | 3 | `addr = top; top = DataMemory[addr]` |
| `STOREI` | нет | 3 | перед командой стек `[..., value, address]`; выполнить `DataMemory[address] = value` |
| `ADD` | нет | 3 | `push(left + right)` |
| `SUB` | нет | 3 | `push(left - right)` |
| `MUL` | нет | 3 | `push(left * right)` |
| `DIV` | нет | 3 | `push(left / right)` |
| `MOD` | нет | 3 | `push(left % right)` |
| `EQ` | нет | 3 | `push(left == right)` |
| `NE` | нет | 3 | `push(left != right)` |
| `LT` | нет | 3 | `push(left < right)` |
| `GT` | нет | 3 | `push(left > right)` |
| `LE` | нет | 3 | `push(left <= right)` |
| `GE` | нет | 3 | `push(left >= right)` |
| `JMP` | code address | 2 | `PC = operand` |
| `JZ` | code address | 2 | если `T == 0`, перейти по адресу; условие снимается со стека |
| `JNZ` | code address | 2 | если `T != 0`, перейти по адресу; условие снимается со стека |
| `CALL` | code address | 2 | сохранить `PC + 4` в return stack, перейти к процедуре |
| `RET` | нет | 2 | вернуться по адресу из return stack |
| `IN` | port | 2 | прочитать токен из порта и положить на стек |
| `OUT` | port | 2 | вывести верхушку стека в порт и снять её со стека |

### Пример дизассемблирования

Отладочный дизассемблер выводит инструкции в формате:

```text
<address> - <HEXCODE> - <mnemonic>
```

Пример:

```text
0000 - 40000004 - JMP 4
0004 - 01000001 - PUSHI 1
0008 - 01000002 - PUSHI 2
0012 - 20000000 - ADD
0016 - 61000002 - OUT 2
```

Для динамической отладки дополнительно создаётся тактовый лог, где для каждого такта указаны `PC`, `MPC`, текущая инструкция, активные сигналы, `SP`, `T`, `F`, `AR`, `R`, состояние стеков и выходной буфер.

---

## Транслятор

Транслятор преобразует исходный код на Mini Lisp в бинарный машинный код стекового процессора и начальное состояние памяти данных.

### Интерфейс командной строки транслятора

Общий запуск транслятора:

```bash
python src/translator.py [--data DATA_JSON] [--disasm DISASM] [--vars VARS] source.lisp output.bin
```

Аргументы:

| Аргумент | Описание |
|---|---|
| `source.lisp` | входной файл с исходным кодом |
| `output.bin` | выходной бинарный файл с машинным кодом |
| `--data DATA_JSON` | сохранить начальную память данных |
| `--disasm DISASM` | сохранить дизассемблированный код |
| `--vars VARS` | сохранить таблицу переменных и их адресов |

Также используется объединённая утилита запуска:

```bash
python src/run_program.py examples/cat.lisp --build-dir build --input examples/cat.in
```

Она выполняет полный цикл:

1. транслирует исходный код;
2. сохраняет бинарный код;
3. сохраняет начальную память данных;
4. сохраняет дизассемблирование;
5. запускает модель процессора;
6. сохраняет вывод, лог и финальную память данных.

Типичные выходные файлы:

```text
build/cat.bin
build/cat.data.json
build/cat.disasm
build/cat.vars
build/cat.out
build/cat.log
build/cat.data.out.json
```

### Этапы работы транслятора

#### 1. Лексический анализ

Исходный текст разбивается на токены:

- `(` и `)`;
- числа;
- символы;
- строковые литералы;
- комментарии пропускаются.

#### 2. Синтаксический анализ

Токены преобразуются в AST из вложенных списков.

Пример:

```lisp
(+ 1 (* 2 3))
```

AST:

```python
["+", 1, ["*", 2, 3]]
```

#### 3. Разделение процедур и основной программы

Верхнеуровневые `(proc ...)` выделяются отдельно. В начало программы помещается `JMP main_start`, чтобы при запуске процессор пропустил тела процедур и начал выполнение основной программы.

#### 4. Компиляция выражений

Каждое выражение компилируется в стековый код, оставляющий результат на стеке.

Пример:

```lisp
(setq x (+ 1 2))
```

порождает примерно:

```text
PUSHI 1
PUSHI 2
ADD
DUP
STORE addr(x)
```

#### 5. Работа со строками

Строковые литералы сохраняются в память данных в формате Pascal string. В машинный код помещается адрес строки.

Например:

```lisp
(print "abc")
```

строка `"abc"` попадает в `Data Memory`, а код печати работает с адресом этой строки.

#### 6. Patch адресов

Для переходов, `if`, `loop` и вызовов процедур транслятор сначала может создать инструкцию с временным операндом `0`, а после того как нужный адрес станет известен, заменить операнд на правильный байтовый адрес.

---

## Модель процессора

Модель процессора выполняет бинарный код с точностью до микротакта. Один такт соответствует исполнению одной микроинструкции из памяти микропрограмм.

### Интерфейс командной строки модели

Запуск модели напрямую:

```bash
python src/machine.py --data program.data.json program.bin --input input.txt --output output.txt --log machine.log --data-output data.out.json
```

Аргументы:

| Аргумент | Описание |
|---|---|
| `program.bin` | бинарный файл машинного кода |
| `--data` | JSON-файл начальной памяти данных |
| `--input` | файл входного потока |
| `--output` | файл выходного потока |
| `--log` | файл тактового журнала |
| `--data-output` | файл финального состояния памяти данных |
| `--tick-limit` | максимальное количество тактов моделирования |
| `--data-memory-size` | размер памяти данных в байтах |

### DataPath

<p align="center">
  <img src="schema/data path.jpg" alt="DataPath" width="850">
</p>

DataPath содержит:

- стек данных;
- память данных;
- АЛУ;
- регистры `SP`, `T`, `F`, `AR`;
- порты ввода-вывода;
- мультиплексоры для выбора источников данных и адресов.

Основные элементы:

| Элемент | Назначение |
|---|---|
| `Stack` | стек данных |
| `SP mux` | выбирает `SP + 4` или `SP - 4` |
| `SP` | указатель вершины стека данных |
| `stack mux` | выбирает значение для записи в стек: immediate, memory, ALU, input, T |
| `T` | верхушка стека |
| `F` | временный регистр второго операнда АЛУ |
| `ALU` | арифметика и сравнения |
| `addr mux` | выбирает адрес из `IR.operand` или `T` |
| `AR` | регистр адреса памяти данных |
| `Data Memory` | однопортовая память данных |
| `I/O` | порты ввода-вывода |

Для команд работы с памятью адрес сначала защёлкивается в `AR`, а обращение к памяти выполняется отдельным микротактом. Это соответствует однопортовой модели памяти.

### ControlUnit

<p align="center">
  <img src="schema/control unit.jpg" alt="DataPath" width="850">
</p>

ControlUnit содержит:

- `PC` — счётчик команд;
- `IR` — регистр инструкции;
- `mPC` — счётчик микропрограммы;
- `opcode_to_mpc` — таблицу адресов начала микропрограмм команд;
- `Microprogram Memory` — память микропрограмм;
- `Control Logic` — декодирование микроинструкции в управляющие сигналы;
- `Return Stack` и регистр `R` для процедур.

Общий цикл работы:

```text
PC -> Instruction Memory -> IR
IR.opcode -> opcode_to_mpc -> mPC
mPC -> Microprogram Memory -> current microinstruction
current microinstruction -> Control Logic -> control signals
control signals -> DataPath / PC / IR / mPC / Return Stack
```

### Основные управляющие сигналы

| Сигнал | Назначение |
|---|---|
| `LATCH_IR` | загрузить инструкцию из `Instruction Memory[PC]` в `IR` |
| `LATCH_MPC` | загрузить новый адрес микроинструкции |
| `LATCH_PC` | загрузить новый адрес инструкции |
| `LATCH_SP` | изменить `SP` |
| `LATCH_T` | загрузить новое значение в `T` |
| `LATCH_F` | загрузить новое значение в `F` |
| `LATCH_AR` | загрузить адрес в `AR` |
| `SELECT_STACK_ADDR` | выбрать адрес записи в стек |
| `WRITE_STACK` | записать значение в стек |
| `SELECT_DATA_ADDRESS` | выбрать источник адреса для `AR` |
| `WRITE_DATA_MEMORY` | записать слово в `Data Memory[AR]` |
| `ALU` | выполнить операцию АЛУ |
| `LATCH_NZ` | обновить флаги результата АЛУ |
| `SELECT_RETURN_STACK_ADDR` | выбрать позицию return stack |
| `WRITE_RETURN_STACK` | записать адрес возврата |
| `LATCH_R` | изменить `R` |
| `READ_IO` | прочитать токен из порта ввода |
| `WRITE_IO` | записать токен в порт вывода |
| `HALT` | остановить моделирование |

### Микропрограммное управление

Микрокод хранится отдельно от модели процессора в `Microprogram Memory`. Для каждой инструкции ISA таблица `opcode_to_mpc` хранит адрес первой микроинструкции.

В таблице приведено содержимое памяти микропрограмм. Один адрес `mPC` соответствует одной микроинструкции, то есть одному такту моделирования. После выборки инструкции выполняется переход по `opcode_to_mpc` к начальному адресу микропрограммы соответствующей команды.

#### Таблица памяти микропрограмм

| Адрес mPC | Команда / этап | Сигналы | Смысл микроинструкции |
|---:|----------------|---|---|
| 000 | `FETCH`        | `latch_ir`<br>`latch_mpc(sel_mpc_opcode)` | IR = InstructionMemory[PC]; mPC = opcode_to_mpc[IR.opcode] |
| 001 | `HALT`         | `halt` | stop simulation |
| 002 | `PUSHI`        | `select_stack_addr(sel_stack_addr_next)`<br>`write_stack(sel_stack_imm)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_sp(sel_sp_next)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | PUSHI: Stack[SP+4] = IR.operand; T = IR.operand; SP += 4 |
| 003 | `DROP`         | `latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | DROP: T = Stack[SP-4]; SP -= 4 |
| 004 | `DUP`          | `select_stack_addr(sel_stack_addr_next)`<br>`write_stack(sel_stack_t)`<br>`latch_sp(sel_sp_next)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | DUP: Stack[SP+4] = T; SP += 4; T is unchanged |
| 005 | `LOAD`         | `select_data_address(sel_addr_operand)`<br>`latch_ar`<br>`latch_mpc(sel_mpc_next)` | LOAD/1: AR = IR.operand |
| 006 | `LOAD` 2       | `select_stack_addr(sel_stack_addr_next)`<br>`write_stack(sel_stack_memory)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_sp(sel_sp_next)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | LOAD/2: Stack[SP+4] = DataMemory[AR]; T = loaded value |
| 007 | `STORE`        | `select_data_address(sel_addr_operand)`<br>`latch_ar`<br>`latch_mpc(sel_mpc_next)` | STORE/1: AR = IR.operand |
| 008 | `STORE` 2      | `write_data_memory(sel_data_in_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | STORE/2: DataMemory[AR] = T; pop value; T = Stack[SP-4] |
| 009 | `LOADI`        | `select_data_address(sel_addr_t)`<br>`latch_ar`<br>`latch_mpc(sel_mpc_next)` | LOADI/1: AR = T |
| 010 | `LOADI` 2      | `select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_memory)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | LOADI/2: Stack[SP] = DataMemory[AR]; T = loaded value |
| 011 | `STOREI`       | `select_data_address(sel_addr_t)`<br>`latch_ar`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | STOREI/1: AR = T(address); pop address; T = value |
| 012 | `STOREI` 2     | `write_data_memory(sel_data_in_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | STOREI/2: DataMemory[AR] = T(value); pop value; T = Stack[SP-4] |
| 013 | `ADD`          | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | ADD: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 014 | `ADD` 2        | `alu(add)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | ADD: Stack[SP] = T op F, T = result |
| 015 | `SUB`          | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | SUB: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 016 | `SUB` 2        | `alu(sub)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | SUB: Stack[SP] = T op F, T = result |
| 017 | `MUL`          | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | MUL: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 018 | `MUL` 2        | `alu(mul)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | MUL: Stack[SP] = T op F, T = result |
| 019 | `DIV`          | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | DIV: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 020 | `DIV` 2        | `alu(div)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | DIV: Stack[SP] = T op F, T = result |
| 021 | `MOD`          | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | MOD: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 022 | `MOD` 2        | `alu(mod)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | MOD: Stack[SP] = T op F, T = result |
| 023 | `EQ`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | EQ: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 024 | `EQ` 2         | `alu(eq)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | EQ: Stack[SP] = T op F, T = result |
| 025 | `NE`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | NE: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 026 | `NE` 2         | `alu(ne)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | NE: Stack[SP] = T op F, T = result |
| 027 | `LT`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | LT: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 028 | `LT` 2         | `alu(lt)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | LT: Stack[SP] = T op F, T = result |
| 029 | `GT`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | GT: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 030 | `GT` 2         | `alu(gt)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | GT: Stack[SP] = T op F, T = result |
| 031 | `LE`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | LE: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 032 | `LE` 2         | `alu(le)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | LE: Stack[SP] = T op F, T = result |
| 033 | `GE`           | `latch_f(sel_f_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_next)` | GE: F = right(old T), T = left(Stack[SP-4]), SP -= 4 |
| 034 | `GE` 2         | `alu(ge)`<br>`select_stack_addr(sel_stack_addr_current)`<br>`write_stack(sel_stack_alu)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_nz`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | GE: Stack[SP] = T op F, T = result |
| 035 | `JMP`          | `latch_pc(sel_pc_operand)`<br>`latch_mpc(sel_mpc_fetch)` | JMP: PC = IR.operand |
| 036 | `JZ`           | `latch_pc(sel_pc_jz_by_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_fetch)` | JZ: branch by T == 0; pop condition; T = Stack[SP-4] |
| 037 | `JNZ`          | `latch_pc(sel_pc_jnz_by_t)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_mpc(sel_mpc_fetch)` | JNZ: branch by T != 0; pop condition; T = Stack[SP-4] |
| 038 | `CALL`         | `select_return_stack_addr(sel_return_stack_next)`<br>`write_return_stack(sel_return_input_pc_next)`<br>`latch_r(sel_r_next)`<br>`latch_pc(sel_pc_operand)`<br>`latch_mpc(sel_mpc_fetch)` | CALL: ReturnStack[R+4] = PC+4; R += 4; PC = IR.operand |
| 039 | `RET`          | `latch_pc(sel_pc_return_stack)`<br>`latch_r(sel_r_prev)`<br>`latch_mpc(sel_mpc_fetch)` | RET: PC = ReturnStack[R]; R -= 4 |
| 040 | `IN`           | `read_io(sel_port_operand)`<br>`select_stack_addr(sel_stack_addr_next)`<br>`write_stack(sel_stack_input)`<br>`latch_t(sel_t_stack_mux)`<br>`latch_sp(sel_sp_next)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | IN: read input[IR.operand]; push value; T = value |
| 041 | `OUT`          | `write_io(sel_port_operand)`<br>`latch_t(sel_t_stack_prev)`<br>`latch_sp(sel_sp_prev)`<br>`latch_pc(sel_pc_next)`<br>`latch_mpc(sel_mpc_fetch)` | OUT: output[IR.operand] = T; pop value; T = Stack[SP-4] |

### Тактовый журнал

Во время моделирования формируется лог. Одна строка соответствует одному такту.

Пример формата:

```text
TICK=000001 | PC=0000 | MPC=000->002 | IR=0000 - 01000001 - PUSHI 1 | SIGNALS=... | SP=... | T=... | F=... | AR=... | R=... | ALU=... | ZF=... | NF=... | STACK=... | RET=... | OUT=...
```

Лог включает:

- номер такта;
- `PC`;
- переход `MPC before -> MPC after`;
- текущую инструкцию;
- активные управляющие сигналы;
- состояние регистров `SP`, `T`, `F`, `AR`, `R`;
- результат АЛУ и флаги;
- вершину стека данных;
- стек возвратов;
- текущий выходной буфер.

### Остановка моделирования

Моделирование завершается в следующих случаях:

1. выполнена команда `HALT`;
2. входной поток закончился во время выполнения `IN`;
3. превышен лимит тактов `tick-limit`;
4. возникла ошибка исполнения, например деление на ноль, выход за границы памяти или обращение к неизвестному порту.

---

## 8. Тестирование

### 0. Формат `golden.yml` файлов

`golden.yml` используется для golden-тестов.  

Общая структура

```yaml
in_source: |-
  исходный код программы на Lisp

in_stdin: |-
  входные данные программы

out_code_hex: |-
  ожидаемый дизассемблер

out_data_dec: |-
  ожидаемая начальная память данных в формате слов по 4 байта:
  01 -   0,   0,   0,   0
  02 -   0,   0,   0,   0

out_stdout: |
  ожидаемый stdout после запуска

out_log: |-
  ожидаемый лог выполнения
```

Все тесты выполняются примерно за 60-80 секунд (такое время из-за программы prob1).

### 1. [hello](golden/hello.yml)

Напечатать Hello World!

### 2. [cat](golden/cat.yml)

Печатать данные, поданные через ввод (размер ввода потенциально бесконечен).

### 3. [hello_user_name](golden/hello_user_name.yml)

Запросить у пользователя его имя, считать его, вывести на экран приветствие.

### 4. [sort](golden/sort.yml)

Пользователь подаёт во входной поток количество чисел `n`, затем сами числа. Программа считывает их через `read-int`, сохраняет в массив в памяти данных с шагом 4 байта, сортирует и выводит в отсортированном формате.

### 5. [double_precision](golden/double_precision.yml)

Программа демонстрирует сложение чисел, которые не помещаются в одно машинное слово.

Алгоритм операций такой:

- Число представляется двумя частями в базе `10000`:

  ```text
  value = hi * BASE + lo
  BASE = 10000
  ```

- Исходные значения:

  ```text
  a = 4294967296 = 429496 * 10000 + 7296
  b = 4294967296 = 429496 * 10000 + 7296
  ```

- Сначала складываются младшие части;

- Если `sum_lo >= BASE`, выполняется перенос;

- Затем складываются старшие части с учётом переноса;

- Получение итогового значения;

- При выводе сначала печатается `sum_hi`, затем `sum_lo`;

- Младшая часть должна занимать ровно 4 цифры, поэтому перед `sum_lo` при необходимости печатаются ведущие нули;

- Вывод программы.

### 6. [prob1](golden/prob1.yml)

Нужно найти максимальный палиндром, который получается при произведении двух трёхзначных чисел.

Можно заметить, что любой шестизначный палиндром имеет вид:

```text
abccba
```

Тогда его можно представить так:

```text
abccba =
100000a + 10000b + 1000c +
100c + 10b + a
```

Сгруппируем слагаемые:

```text
= 100001a + 10010b + 1100c
```

Вынесем общий множитель `11`:

```text
= 11 * (9091a + 910b + 100c)
```

Следовательно, любой шестизначный палиндром делится на `11`.

Значит, в произведении двух трёхзначных чисел хотя бы один множитель должен делиться на `11`, что используется в программе для сокращения количества проверок.

### 7. [factorial](golden/factorial.yml)

Реализован факториал через рекурсию.

---

## Работа со строками

Строки хранятся в памяти данных в формате Pascal string. Первое машинное слово содержит длину строки, следующие машинные слова содержат коды символов.

```text
address + 0  : length
address + 4  : char 0
address + 8  : char 1
address + 12 : char 2
...
```

Встроенные строковые формы языка не изменяют Python-строку напрямую. Они транслируются в обычные инструкции стековой машины.

Например:

```lisp
(pstr-set s 1 88)
```

сначала кладёт на стек новое значение символа, затем вычисляет адрес нужного символа:

```text
char_addr = s + 4 + index * 4
```

Перед `STOREI` стек имеет вид:

```text
[..., 88, char_addr]
```

Затем `STOREI` записывает значение в `DataMemory[char_addr]`.

Также работу со строками можно реализовать пользовательской процедурой на самом языке:

```lisp
(proc my-print-pstr (s)
  (setq i 0)
  (setq len (load-at s))

  (loop (< i len)
    (print-char (load-at (+ (+ s 4) (* i 4))))
    (setq i (+ i 1))))

(setq msg "hello")
(call my-print-pstr msg)
```

В этом примере строка передаётся в процедуру как адрес первого слова. Процедура читает длину через `load-at`, затем в цикле вычисляет адрес каждого символа, читает его из памяти и выводит через `print-char`.
