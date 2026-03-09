# Grade Calculation — A-Level Business Studies

Last updated: March 2026

## Assignment Weights

| Component         | Column in CSV      | Weight |
|-------------------|--------------------|--------|
| Unit 1 Test       | unit1_test         | 10%    |
| Unit 2 Test       | unit2_test         | 10%    |
| Unit 3 Essay      | unit3_essay        | 15%    |
| Unit 4 Presentation | unit4_presentation | 15%  |
| Mock Exam         | mock_exam          | 20%    |
| Final Exam        | final_exam         | 30%    |

All scores in the CSV are percentages (0–100).

## How to Calculate the Weighted Average

Use python3 via bash. Never calculate from memory.

Example bash command:
```
python3 -c "
u1=94; u2=92; u3=91; u4=90; mock=93; final=89
weighted = u1*0.10 + u2*0.10 + u3*0.15 + u4*0.15 + mock*0.20 + final*0.30
print(f'Weighted average: {weighted:.2f}%')
"
```

Substitute the actual student scores from the CSV row.

## UK A-Level Grade Boundaries

| Grade | Minimum weighted average |
|-------|--------------------------|
| A*    | 90%                      |
| A     | 80%                      |
| B     | 70%                      |
| C     | 60%                      |
| D     | 50%                      |
| E     | 40%                      |
| U     | below 40%                |

## Rules

- Always calculate to 2 decimal places before applying the boundary table
- The predicted grade is the boundary the weighted average meets or exceeds
- If the weighted average is exactly on a boundary (e.g. 80.00%), award the higher grade (A in this case)
- Do not round the weighted average up to a boundary — use the exact calculated value
- Record both the weighted average and the derived grade in the output
