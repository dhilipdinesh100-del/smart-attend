import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database
import face_engine

def main():
    print("=" * 60)
    print(" SmartAttend — Train LBPH Face Recognition Model")
    print("=" * 60)
    
    database.init_db()
    
    print("\n[INFO] Reading dataset images from data/faces/ ...")
    res = face_engine.train_lbph_model()
    
    if res["success"]:
        print(f"\n[SUCCESS] {res['message']}")
        print(f"  - Total Students Trained: {res['students_count']}")
        print(f"  - Total Face Images Used: {res['images_count']}")
        print(f"  - Model Saved At: {res['model_path']}")
    else:
        print(f"\n[ERROR] {res['message']}")
        sys.exit(1)

if __name__ == "__main__":
    main()
