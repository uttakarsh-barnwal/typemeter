#!/usr/bin/env python3
import sqlite3
import datetime
import typemeter_db

def fit_level(cursor, level):
    """Calculates population mean/variance of error rates at a level and updates global priors using Method-of-Moments."""
    cursor.execute(f"SELECT mistakes, total FROM {level}_stats")
    rows = cursor.fetchall()
    
    if len(rows) < 2:
        print(f"[!] Prior-fitting for {level} skipped: insufficient data (sample size = {len(rows)})")
        return
        
    rates = [row["mistakes"] / row["total"] for row in rows]
    mean = sum(rates) / len(rates)
    
    # Calculate sample variance
    variance = sum((r - mean) ** 2 for r in rates) / (len(rates) - 1)
    
    if variance <= 1e-9:
        print(f"[!] Prior-fitting for {level} skipped: variance too low ({variance})")
        return
        
    val = mean * (1.0 - mean)
    if val <= variance:
        print(f"[!] Prior-fitting for {level} skipped: mean * (1 - mean) <= variance (degenerate parameters)")
        return
        
    common = val / variance - 1.0
    alpha = mean * common
    beta = (1.0 - mean) * common
    
    if alpha <= 0 or beta <= 0:
        print(f"[!] Prior-fitting for {level} skipped: non-positive alpha/beta ({alpha}, {beta})")
        return
        
    now_str = datetime.datetime.utcnow().isoformat()
    
    cursor.execute("""
        INSERT INTO global_priors (level, alpha, beta, fitted_at, sample_size)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(level) DO UPDATE SET
            alpha = excluded.alpha,
            beta = excluded.beta,
            fitted_at = excluded.fitted_at,
            sample_size = excluded.sample_size
    """, (level, alpha, beta, now_str, len(rows)))
    print(f"[*] Fitted {level} prior: alpha={alpha:.4f}, beta={beta:.4f} (n={len(rows)})")

def main():
    print("==================================================")
    print("      TypeMeter Global Prior Fitting Job          ")
    print("==================================================")
    
    conn = typemeter_db.get_db("typemeter.db")
    cursor = conn.cursor()
    
    try:
        fit_level(cursor, "unigram")
        fit_level(cursor, "bigram")
        fit_level(cursor, "trigram")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[!] Error fitting priors: {e}")
    finally:
        conn.close()
        
if __name__ == "__main__":
    main()
