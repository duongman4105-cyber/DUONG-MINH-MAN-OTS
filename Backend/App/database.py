from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# Thay YOUR_PASSWORD bằng mật khẩu tài khoản root MySQL của bạn
SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:04012005@127.0.0.1:3306/mtmct_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Hàm tạo session để truy vấn CSDL cho mỗi request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()