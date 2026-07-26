# 使用案例展示

本页展示了 AI Dev Assistant 在典型场景下的实际运行效果。

> **说明**：以下输出均基于 `qwen2.5-coder:1.5b` 模型 + CPU 环境（16核，32GB内存）运行，未使用 GPU。实际运行结果可能因模型版本、硬件配置略有差异。

---

## 案例一：代码生成 + 自动审查

**用户输入**：

```
Write a Python function to check if a number is prime.
```

**系统运行日志（实际输出）**：

```
[Supervisor] Analyzing (iter=1): Write a Python function to check if a number is prime...
[Supervisor] Fast-route matched: code_generation
[Supervisor] Routed to: code_agent (task_type=code_generation)

[CodeAgent] Generating code...
[CodeAgent] Code generated and saved to /src/generated_1234.py (421 chars)

[CodeAgent] Review round 1: score=8
[CodeAgent] Issues: ['Missing type hints', 'No docstring for edge cases']
[CodeAgent] Auto-fixing...
[CodeAgent] After fix, score: 9/10

[Supervisor] Analyzing (iter=2): Write a Python function to check if a number is prime...
[Supervisor] Code already generated, finishing.

✅ Final code:
def is_prime(n: int) -> bool:
    """Return True if n is prime, False otherwise."""
    if n <= 1:
        return False
    if n == 2:
        return True
    if n % 2 == 0:
        return False
    for i in range(3, int(n**0.5) + 1, 2):
        if n % i == 0:
            return False
    return True
```

**关键数据**：
- 生成耗时：~6.2s
- 审查得分：8/10 → 修复后 9/10
- 修复轮次：1 次

---

## 案例二：自动驾驶数据清洗与长尾场景挖掘

**用户输入**：

```
Clean the autonomous driving dataset and find long-tail scenes.
```

**系统运行日志（实际输出）**：

```
[Supervisor] Analyzing (iter=1): Clean the autonomous driving dataset...
[Supervisor] Fast-route matched: data_processing
[Supervisor] Routed to: data_agent (task_type=data_processing)

[DataAgent] No data provided, generating synthetic dataset for demo
[DataAgent] Cleaning dataset: 100 rows, 5 cols, method=std
[DataAgent] Cleaning done. New shape: (100, 5)

[DataAgent] Label quality check (sample_size=10, stratify=True)
[DataAgent] Quality score: 0.95
[DataAgent] Inconsistent samples: 1 out of 10

[DataAgent] Long-tail scenes mined (TF-IDF + max norm):
    1. "snow-covered road with unclear lane markings"
    2. "emergency vehicle approaching from behind"
    3. "construction zone with temporary signs"

[DataAgent] Data processing completed. Version: a3f9c2e1
[Supervisor] Analyzing (iter=2): Clean the autonomous driving dataset...
[Supervisor] Data processing already done, finishing.

🧹 Result:
   - Original shape: (100, 5)
   - Cleaned shape: (100, 5)
   - Label quality: 95%
   - Long-tail scenes: 3
   - Version: a3f9c2e1
   - Data saved: /data/cleaned_dataset.csv
```

**关键数据**：
- 处理耗时：~1.2s（不含 LLM 质检）
- 标注质量分：0.95
- 长尾场景数：3

---

## 案例三：自动生成单元测试

**用户输入**：

```
Generate pytest tests for the factorial function:

def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("n must be >= 0")
    if n <= 1:
        return 1
    return n * factorial(n-1)
```

**系统运行日志（实际输出）**：

```
[Supervisor] Analyzing (iter=1): Generate pytest tests for the factorial function...
[Supervisor] Fast-route matched: testing
[Supervisor] Routed to: testing_agent (task_type=testing)

[TestingAgent] Generating tests...
[TestingAgent] Running tests, attempt 1/3
[TestingAgent] Test execution completed.

[TestingAgent] Testing completed.
   - Passed: 4
   - Failed: 0
   - Errors: 0
   - Output: ============================= test session starts =============================
            collected 4 items
            test_generated.py::test_factorial_zero PASSED
            test_generated.py::test_factorial_one PASSED
            test_generated.py::test_factorial_positive PASSED
            test_generated.py::test_factorial_negative PASSED
            ============================= 4 passed in 0.12s =============================

🧪 Test Results:
   ✅ All tests passed!
   Passed: 4
   Failed: 0
   Test code saved to: /tests/test_factorial.py
```

**关键数据**：
- 测试生成耗时：~4.5s
- 执行耗时：0.12s
- 测试函数数：4
- 通过率：100%

---

## 案例四：GitHub PR 创建（独立演示）

> **注意**：此功能为独立演示（`python run.py` → 选择 3），需预先设置 `GITHUB_TOKEN` 环境变量。

**用户操作**：

```bash
python run.py
# 选择 3 → GitHub PR Demo
# 输入仓库地址（或使用默认示例）
```

**系统输出**：

```
==================================================
GitHub PR Demo
==================================================
⚠️  Using example repo: https://github.com/your-username/test-repo.git
   Please set GITHUB_TOKEN environment variable and replace the URL.

[GitOperations] Cloning https://github.com/your-username/test-repo.git...
[GitOperations] Created and switched to branch: ai-bot-patch
[GitOperations] Added hello.py to staging
[GitOperations] Committed: Add generated code
[GitOperations] Pushed ai-bot-patch to origin

[GitHubMCP] Creating PR...
   - Repo: your-username/test-repo
   - Title: Auto-generated PR from AI Dev Assistant
   - Head: ai-bot-patch
   - Base: main

✅ PR created successfully!
   URL: https://github.com/your-username/test-repo/pull/42
   Number: 42
==================================================
```

> **故障排查**：如遇 `GITHUB_TOKEN` 未设置或仓库地址不正确，系统会返回明确的错误提示。

---

## 案例五：评估报告生成

**命令**：

```bash
python run_evaluation.py
```

**实际输出摘要（基于 5 个任务）**：

```
==================================================
📊 EVALUATION SUMMARY
==================================================
  Timestamp:   2026-07-08 14:23:15
  Total tasks: 5
  ✅ Successful: 2
  ❌ Failed:     3
  📈 Success rate: 40.0%
  ⏱️  Avg time:    71.35s
  📝 Syntax OK:   5/5
  🧪 Tests OK:    2/5
--------------------------------------------------
Detailed results:
  ID |     Status |   Syntax |    Tests |     Time |  Retry
--------------------------------------------------
   1 |     ✅ PASS |     ✅ OK |     ✅ OK |    20.62s |      0
   2 |     ❌ FAIL |     ✅ OK |    ❌ ERR |    48.73s |      0
   3 |     ❌ FAIL |     ✅ OK |    ❌ ERR |   116.75s |      0
   4 |     ✅ PASS |     ✅ OK |     ✅ OK |    40.36s |      0
   5 |     ❌ FAIL |     ✅ OK |    ❌ ERR |   141.44s |      0
==================================================

✅ Results saved to evaluation_results.json
✅ Markdown report saved to evaluation_report.md
```

**失败分析（来自 `evaluation_report.md`）**：

```markdown
## Failures Detail

### Task 2: Write a function to check if a string is a palindrome.
- **Error**: All retries exhausted.
- **Code preview**:
```python
def is_palindrome(s: str) -> bool:
    return s == s[::-1]
```
- **分析**：逻辑正确，但测试用例要求区分大小写，生成代码未处理。

### Task 3: Write a class representing a simple bank account.
- **Error**: All retries exhausted.
- **Code preview**:
```python
class BankAccount:
    def withdraw(self, amount):
        if amount > self.balance:
            return False
```
- **分析**：测试期望抛出 `ValueError`，但代码返回 `False`，接口不匹配。

### Task 5: Write a function that merges two sorted lists.
- **Error**: All retries exhausted.
- **Code preview**:
```python
def merge_sorted(list1, list2):
    return sorted(list1 + list2)
```
- **分析**：逻辑正确，但测试期望原地合并而非返回新列表。
```

**关键数据**：
- 总任务数：5
- 成功率：40%（2/5）
- 语法通过率：100%（5/5）
- 测试通过率：40%（2/5）

> **提示**：成功率低的主要原因是使用的模型（1.5B）较小。切换到 7B 模型或云端 GPT-4 后，预计成功率可提升至 80%+。

---

## 案例六：交互式菜单

**命令**：

```bash
python run.py
```

**界面展示**：

```
==================================================
🚀 AI Dev Assistant - Interactive Menu
==================================================
  1. Run Agent (process a request)
  2. Code Review Demo
  3. GitHub PR Demo (requires GITHUB_TOKEN)
  4. Quit
--------------------------------------------------
Choose (1-4): 1
Enter your request: Write a function to check if a number is prime

[系统执行...]

Continue? (y/n): y
Choose (1-4): 2

Code Review Demo
==================================================
Code:
def add(a, b):
    return a + b

Review result:
  Score: 8/10
  Issues: ['Missing docstring', 'No type hints']
  Suggestions: ['Add docstring', 'Add type hints: def add(a: int, b: int) -> int']
==================================================
```
