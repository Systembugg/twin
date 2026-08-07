from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import List, Dict, Optional

@dataclass
class Expense:
    amount: float
    category: str

class Tracker:
    def __init__(self, storage_file: str = "expenses.json"):
        self.storage_file = Path(storage_file)
        self.expenses: List[Expense] = []
        self.load()

    def add(self, amount: float, category: str) -> None:
        self.expenses.append(Expense(amount=float(amount), category=category))
        self.save()

    def total(self) -> float:
        return sum(e.amount for e in self.expenses)

    def by_category(self) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for e in self.expenses:
            result[e.category] = result.get(e.category, 0.0) + e.amount
        return result

    def top(self) -> Optional[str]:
        cat_map = self.by_category()
        if not cat_map:
            return None
        return max(cat_map.items(), key=lambda x: x[1])[0]

    def save(self) -> None:
        data = [asdict(e) for e in self.expenses]
        self.storage_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> None:
        if self.storage_file.exists():
            try:
                data = json.loads(self.storage_file.read_text(encoding="utf-8"))
                self.expenses = [Expense(**item) for item in data]
            except json.JSONDecodeError:
                self.expenses = []
        else:
            self.expenses = []
