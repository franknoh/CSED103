# Assignment 1: Parking Fee Calculator

Suho Noh | 20250041 | Electrical Engineering | HEMOS: franknoh

**Environment.** VS Code 1.130.0 on Ubuntu 24.04.5 (WSL2).
Verified on Windows with the Visual Studio 2022 v143 toolset,
MSVC 19.44.35229, C17. PPY 0.7.0 generates standalone C; the shared
`csed103` tool builds, tests, and captures the example sessions.

## Design

**Problem 1.** A loop processes all N cars. `parking_fee` returns 0 for
up to 30 minutes; otherwise, `(minutes - 30 + 9) / 10` rounds the excess
up to 10-minute units. Each unit costs 500 won, capped at 5000 won.
`total_fee` accumulates fees; `free_cars` counts zero-fee cars.

**Problem 2.** A loop checks every minute from 0 through 1440.
Whenever `parking_fee(minute) <= budget`, it updates `maximum_time`.
The final value is the longest affordable time, including equality.

## Results and verification

**Problem 1:** Input N = 5 and times 0, 30, 31, 41, 131.
Expected fees: 0, 0, 500, 1000, 5000 won; total 6500 won and 2 free cars.
The recorded output below matches these results.

![Problem 1 terminal session](out/examples/problem1.png){width=3.3in}

**Problem 2:** Input budget = 750 won. Expected maximum: 40 minutes
(500 won); 41 minutes costs 1000 won. The recorded output matches.

![Problem 2 terminal session](out/examples/problem2.png){width=3.3in}

All **44 tests passed** on MSVC (Problem 1: 9; Problem 2: 35), with no
compiler warnings. Tests cover billing boundaries, the fee cap, 20 cars,
non-multiple budgets, and INT_MAX. Budgets 0, 4999, and 5000 correctly
allow 30, 120, and 1440 minutes. Captures are automatically rendered from actual
pseudoconsole sessions, including echoed example input. `_CRT_SECURE_NO_WARNINGS` enables `scanf`
without Visual Studio's deprecation diagnostic.
