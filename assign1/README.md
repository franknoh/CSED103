# Assignment 1: Parking Fee Calculator

Suho Noh (20250041), Electrical Engineering. HEMOS ID: `franknoh`.

## Environment

VS Code 1.130.0, Ubuntu 24.04.5 on WSL2, and GCC 13.3.0 (C17).
C/C++ sources are generated from `ppy/` with PPY 0.3.5 using
`emit --standalone --unsafe --int-width 32 --format`.

## Design

- **Problem 1:** Loop over the cars, calculate each fee, and accumulate the
  total and free-car count. Parking up to 30 minutes is free. Otherwise,
  round the excess time up to 10-minute units, charge 500 won per unit,
  and cap the fee at 5000 won.
- **Problem 2:** Check every minute from 0 through 1440. Keep the largest
  time whose fee does not exceed the budget, including equality.

## Verification

All 44 cases pass with GCC: 9 for Problem 1 and 35 for Problem 2.
Coverage includes free-period and billing boundaries, the fee cap,
20 cars, non-multiple budgets, and the maximum 32-bit signed integer budget.

- **Problem 1 example:** Durations 0, 30, 31, 41, and 131 produce fees
  0, 0, 500, 1000, and 5000 won: total 6500 won, with 2 free cars.
- **Problem 2 examples:** Budgets 0, 750, 4999, and 5000 allow
  30, 40, 120, and 1440 minutes, respectively.

Expected `.out` files include prompts but not echoed input.
MSVC has not been tested locally.

## Commands

```sh
csed103 build ppy assign1
csed103 test assign1
csed103 build all assign1
```

**Reference:** [Assignment specification](assets/Assn1.pdf), pages 1-4.
