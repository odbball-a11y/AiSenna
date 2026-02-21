"""Test CSV reading"""
import pandas as pd
import os

csv_dir = "senna_ai/opponent_laps/Silverstone Grand Prix Circuit - ELMS"
csv_files = [f for f in os.listdir(csv_dir) if f.endswith('.csv')]
print(f"Found {len(csv_files)} CSV files")

if csv_files:
    csv_path = os.path.join(csv_dir, csv_files[0])
    print(f"Reading: {csv_path}")
    
    # First, let's see the raw file structure
    with open(csv_path, 'r') as f:
        lines = []
        for i in range(20):  # Read first 20 lines
            line = f.readline()
            if not line:
                break
            lines.append(line.strip())
    
    print("\nFirst 20 lines:")
    for i, line in enumerate(lines):
        print(f"{i}: {line}")
    
    # Now try to find where data starts
    print("\nLooking for data header...")
    for i, line in enumerate(lines):
        if 'lapdistance' in line.lower():
            print(f"Found header at line {i}: {line}")
            header_line = i
            break
    else:
        print("No header found")
        header_line = 5  # Try default
    
    # Try reading with skiprows
    try:
        df = pd.read_csv(csv_path, skiprows=header_line)
        print(f"\nSuccessfully read CSV with {len(df)} rows")
        print(f"Columns: {list(df.columns)}")
        
        if 'world_x' in df.columns:
            print(f"\nFirst few world_x values:")
            print(df['world_x'].head())
            print(f"\nFirst few world_z values:")
            print(df['world_z'].head())
        else:
            print("\nNo world_x column found")
            
    except Exception as e:
        print(f"\nError reading CSV: {e}")
