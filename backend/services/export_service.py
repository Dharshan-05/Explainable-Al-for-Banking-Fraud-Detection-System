import csv
import io
from typing import List
from models.transaction import Transaction

def generate_transactions_csv(transactions: List[Transaction]) -> bytes:
    """
    Generates a CSV binary stream for a list of transactions.
    
    Headers:
    transaction_id, amount, risk_level, fraud_score, status, reviewed_by, review_notes, created_at
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\n')
    
    # Write headers
    writer.writerow([
        "transaction_id", 
        "amount", 
        "risk_level", 
        "fraud_score", 
        "status", 
        "reviewed_by", 
        "review_notes", 
        "created_at"
    ])
    
    # Write rows
    for tx in transactions:
        writer.writerow([
            str(tx.id),
            tx.amount,
            tx.risk_level.value if tx.risk_level else "",
            tx.fraud_score if tx.fraud_score is not None else "",
            tx.status.value if tx.status else "",
            tx.reviewed_by or "",
            tx.review_notes or "",
            tx.created_at.isoformat() if tx.created_at else ""
        ])
        
    return output.getvalue().encode('utf-8')
