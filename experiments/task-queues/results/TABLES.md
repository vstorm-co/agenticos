
### probe

| variant | cold start s |
|---|---|
| celery-prefork | 8.6 |
| celery-prefork | 9.1 |
| celery-prefork | 10.4 |
| celery-threads | 9.6 |
| celery-threads | 12.6 |
| celery-threads | 6.8 |
| dramatiq | 5.2 |
| dramatiq | 6.5 |
| dramatiq | 5.8 |
| hatchet | 9.1 |
| hatchet | 16.2 |
| hatchet | 10.7 |
| hatchet-fair | 13.7 |
| pgqueue | 6.0 |
| pgqueue | 4.4 |
| pgqueue | 10.3 |
| pgqueue-fair | 5.0 |
| prefect-serve | 20.3 |
| prefect-serve | 19.2 |
| prefect-serve | 20.2 |
| prefect-serve-20 | 28.4 |
| prefect-serve-pg | 17.4 |
| prefect-tasks | 4.7 |
| prefect-tasks | 9.2 |
| prefect-tasks | 5.7 |
| procrastinate | 4.7 |
| procrastinate | 8.1 |
| procrastinate | 7.6 |
| saq | 5.2 |
| saq | 6.4 |
| saq | 8.0 |
| taskiq | 5.6 |
| taskiq | 9.5 |
| taskiq | 8.0 |

### workflow

| variant | steps done | lost | hop p50 s | hop p95 s | run p50 s | run p95 s | makespan s | steps/s | workers CPU avg % | workers RAM max MB | stack CPU avg % | stack RAM max MB | WAL bytes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| celery-prefork | 500 | 0 | 0.05 | 0.13 | 1.0 | 1.0 | 1.0 | 484.5 | 0 | 1294 | 0 | 1354 | 614928 |
| celery-threads | 500 | 0 | 0.06 | 0.10 | 0.9 | 1.0 | 1.0 | 505.7 | 0 | 325 | 0 | 372 | 615088 |
| dramatiq | 500 | 0 | 0.02 | 0.05 | 0.4 | 0.4 | 0.4 | 1338.0 | 0 | 583 | 0 | 630 | 585656 |
| hatchet | 500 | 0 | 0.42 | 0.82 | 5.3 | 5.4 | 5.5 | 91.7 | 48 | 642 | 278 | 1436 | 14948512 |
| pgqueue | 500 | 0 | 0.03 | 0.06 | 1.0 | 1.0 | 1.0 | 505.5 | 0 | 288 | 0 | 492 | 1066112 |
| prefect-serve (timed out) | 273 | - | 218.04 | 246.46 | - | - | 1228.3 | 0.2 | 228 | 1736 | 258 | 2093 | 743192 |
| prefect-serve-20 (timed out) | 0 | - | - | - | - | - | 1234.8 | 0.0 | 67 | 4095 | 80 | 4440 | 47384 |
| prefect-serve-pg (timed out) | 232 | - | 195.33 | 398.67 | - | - | 1180.2 | 0.2 | 227 | 1734 | 264 | 2134 | 39405840 |
| prefect-tasks | 500 | 0 | 2.60 | 6.82 | 44.5 | 44.9 | 44.9 | 11.1 | 69 | 861 | 107 | 1153 | 622488 |
| procrastinate | 500 | 0 | 0.05 | 0.06 | 0.6 | 0.6 | 0.6 | 828.5 | 0 | 294 | 0 | 369 | 1857000 |
| saq | 500 | 0 | 0.01 | 0.05 | 0.6 | 0.6 | 0.6 | 817.7 | 0 | 564 | 0 | 564 | 553728 |
| taskiq | 500 | 0 | 0.01 | 0.02 | 0.5 | 0.5 | 0.5 | 948.4 | 0 | 184 | 0 | 184 | 578208 |

### mix

| variant | done | lost | agent wait p50 | agent wait p95 | parse wait p50 | parse wait p95 | sweeps | sweep max dev s | workers CPU avg % | workers RAM max MB | stack CPU avg % | stack RAM max MB | WAL bytes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| celery-prefork | 742 | 0 | 148.37 | 279.42 | 147.40 | 278.95 | 10 | 63.1 | 11 | 1309 | 14 | 1385 | 1238152 |
| celery-threads | 732 | 0 | 0.01 | 0.04 | 0.00 | 0.04 | 5 | 0.0 | 19 | 374 | 22 | 468 | 1142528 |
| dramatiq | 730 | 0 | 0.11 | 0.42 | 0.12 | 0.41 | 0 | - | 19 | 590 | 22 | 658 | 1018792 |
| hatchet | 745 | 0 | 0.01 | 0.27 | 0.01 | 0.29 | 5 | 1.0 | 20 | 642 | 37 | 1245 | 28244248 |
| pgqueue | 726 | 0 | 0.01 | 0.57 | 0.01 | 0.91 | 5 | 0.0 | 23 | 294 | 30 | 412 | 1858872 |
| prefect-tasks | 731 | 0 | 0.10 | 2.15 | 0.12 | 2.44 | 0 | - | 27 | 339 | 42 | 654 | 1106984 |
| procrastinate | 728 | 0 | 0.01 | 0.61 | 0.01 | 0.45 | 6 | 29.4 | 19 | 296 | 22 | 393 | 3251880 |
| saq | 741 | 0 | 0.00 | 0.26 | 0.00 | 0.20 | 6 | 0.6 | 20 | 569 | 23 | 658 | 991824 |
| taskiq | 722 | 0 | 0.00 | 0.01 | 0.00 | 0.01 | 6 | 0.0 | 17 | 883 | 20 | 957 | 1020968 |

### tenants

| variant | done | lost | duplicated | re-executed | small org wait p50 | small org wait p95 | small org wait max | longest stall s | makespan s | workers CPU avg % | workers RAM max MB | stack CPU avg % | stack RAM max MB | WAL bytes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| celery-prefork | 1090 | 0 | 0 | 6 | 11.63 | 50.33 | 54.7 | 39.5 | 129.9 | 203 | 3017 | 223 | 3433 | 1413864 |
| celery-threads | 1090 | 0 | 0 | 1 | 0.01 | 12.45 | 16.9 | 37.8 | 128.0 | 190 | 2060 | 205 | 2491 | 1408808 |
| dramatiq | 1090 | 0 | 0 | 0 | 0.22 | 12.62 | 17.1 | 17.8 | 90.0 | 187 | 2324 | 200 | 2762 | 1335072 |
| hatchet | 1090 | 0 | 0 | 1 | 0.03 | 21.33 | 25.8 | 27.8 | 93.2 | 46 | 1225 | 118 | 2596 | 30496392 |
| hatchet-fair | 1090 | 0 | 0 | 10 | 0.05 | 18.33 | 22.8 | 24.0 | 91.8 | 220 | 2366 | 294 | 3603 | 33082784 |
| pgqueue | 1090 | 0 | 0 | 1 | 0.03 | 11.05 | 15.5 | 17.5 | 90.2 | 206 | 2017 | 241 | 2799 | 2470288 |
| pgqueue-fair | 1090 | 0 | 137 | 141 | 0.02 | 10.05 | 14.2 | 15.4 | 90.4 | 210 | 2018 | 231 | 2780 | 2905408 |
| prefect-tasks (timed out) | 1088 | - | 0 | 0 | 0.08 | 8.63 | 13.0 | 15.8 | 516.6 | 11 | 806 | 28 | 1124 | 1691256 |
| procrastinate (timed out) | 1089 | - | 0 | 0 | 0.01 | 11.06 | 15.5 | 17.5 | 89.8 | 22 | 876 | 33 | 1312 | 5246984 |
| saq | 1090 | 0 | 0 | 1 | 0.00 | 10.02 | 14.5 | 551.5 | 640.9 | 138 | 2292 | 149 | 2744 | 1512760 |
| taskiq | 1090 | 0 | 0 | 0 | 0.02 | 12.03 | 16.3 | 17.5 | 90.2 | 189 | 2608 | 206 | 3037 | 1308864 |
