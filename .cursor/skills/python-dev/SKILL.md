---
name: python-dev
description: Python development with modern best practices, type hints, FastAPI/Flask APIs, async programming, testing with pytest, and project structure. Use when writing Python code, building Python APIs, working with FastAPI or Flask, or when the user mentions Python development.
---

# Python Developer

## Project Structure

```
project/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py
│   ├── routes/
│   │   ├── __init__.py
│   │   └── users.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── user_service.py
│   └── utils/
│       ├── __init__.py
│       └── validators.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_users.py
│   └── fixtures/
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

## Type Hints and Modern Python

Always use type hints for better IDE support and code clarity:

```python
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from pydantic import BaseModel

# Function type hints
def process_user(
    user_id: int,
    name: str,
    email: Optional[str] = None,
    tags: List[str] | None = None  # Python 3.10+ union syntax
) -> Dict[str, Any]:
    """Process user data and return formatted result."""
    return {
        "id": user_id,
        "name": name,
        "email": email,
        "tags": tags or []
    }

# Class with type hints
class User:
    def __init__(self, id: int, name: str, created_at: datetime) -> None:
        self.id = id
        self.name = name
        self.created_at = created_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat()
        }

# Pydantic models for validation
class UserCreate(BaseModel):
    name: str
    email: str
    age: Optional[int] = None
    
    class Config:
        from_attributes = True  # Formerly orm_mode
```

## FastAPI REST API

```python
# main.py
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional
import uvicorn

app = FastAPI(
    title="My API",
    description="API description",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    email: EmailStr
    age: Optional[int] = Field(None, ge=0, le=150)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)

class UserResponse(UserBase):
    id: int
    created_at: str
    
    class Config:
        from_attributes = True

# Dependency injection
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Validate token and return user."""
    user = await verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return user

# Routes
@app.get("/")
async def root() -> dict:
    return {"message": "API is running"}

@app.get("/users", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 10,
    search: Optional[str] = None
) -> List[UserResponse]:
    """Get list of users with pagination."""
    users = await user_service.get_users(skip=skip, limit=limit, search=search)
    return users

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int) -> UserResponse:
    """Get user by ID."""
    user = await user_service.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found"
        )
    return user

@app.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate) -> UserResponse:
    """Create a new user."""
    try:
        new_user = await user_service.create_user(user)
        return new_user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@app.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user: UserBase,
    current_user: dict = Depends(get_current_user)
) -> UserResponse:
    """Update existing user (protected route)."""
    updated_user = await user_service.update_user(user_id, user)
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found"
        )
    return updated_user

@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
) -> None:
    """Delete user (protected route)."""
    success = await user_service.delete_user(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found"
        )

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

## Async/Await Patterns

```python
import asyncio
import aiohttp
from typing import List, Dict, Any

# Async function
async def fetch_data(url: str) -> Dict[str, Any]:
    """Fetch data from URL asynchronously."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

# Parallel async operations
async def fetch_multiple(urls: List[str]) -> List[Dict[str, Any]]:
    """Fetch multiple URLs in parallel."""
    tasks = [fetch_data(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out errors
    return [r for r in results if not isinstance(r, Exception)]

# Async context manager
class DatabaseConnection:
    async def __aenter__(self):
        self.connection = await connect_to_db()
        return self.connection
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.connection.close()

# Usage
async def main():
    async with DatabaseConnection() as db:
        result = await db.query("SELECT * FROM users")
        return result
```

## Database Patterns (SQLAlchemy)

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, select
from datetime import datetime

# Setup
Base = declarative_base()
engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Model
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Dependency for FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

# Service layer
class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_users(
        self,
        skip: int = 0,
        limit: int = 10,
        search: Optional[str] = None
    ) -> List[User]:
        """Get users with optional search."""
        query = select(User)
        
        if search:
            query = query.where(User.name.ilike(f"%{search}%"))
        
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def create_user(self, user_data: dict) -> User:
        """Create new user."""
        user = User(**user_data)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def update_user(self, user_id: int, user_data: dict) -> Optional[User]:
        """Update existing user."""
        user = await self.get_user(user_id)
        if not user:
            return None
        
        for key, value in user_data.items():
            setattr(user, key, value)
        
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def delete_user(self, user_id: int) -> bool:
        """Delete user."""
        user = await self.get_user(user_id)
        if not user:
            return False
        
        await self.db.delete(user)
        await self.db.commit()
        return True
```

## Error Handling

```python
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Custom exceptions
class AppException(Exception):
    """Base application exception."""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)

class NotFoundError(AppException):
    """Resource not found."""
    pass

class ValidationError(AppException):
    """Validation failed."""
    pass

# Error handling decorator
from functools import wraps

def handle_errors(func):
    """Decorator to handle common errors."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except NotFoundError as e:
            logger.error(f"Not found: {e.message}")
            raise HTTPException(status_code=404, detail=e.message)
        except ValidationError as e:
            logger.error(f"Validation error: {e.message}")
            raise HTTPException(status_code=400, detail=e.message)
        except Exception as e:
            logger.exception(f"Unexpected error in {func.__name__}")
            raise HTTPException(status_code=500, detail="Internal server error")
    return wrapper

# Usage
@handle_errors
async def get_user_data(user_id: int) -> dict:
    user = await user_service.get_user(user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    return user.to_dict()
```

## Testing with Pytest

```python
# conftest.py
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

@pytest.fixture
async def db_session():
    """Create test database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession)
    async with AsyncSessionLocal() as session:
        yield session
    
    await engine.dispose()

@pytest.fixture
async def client(db_session):
    """Create test client with database override."""
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()

# test_users.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_user(client: AsyncClient):
    """Test user creation."""
    response = await client.post(
        "/users",
        json={"name": "John Doe", "email": "john@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "John Doe"
    assert "id" in data

@pytest.mark.asyncio
async def test_get_user(client: AsyncClient):
    """Test getting user by ID."""
    # Create user first
    create_response = await client.post(
        "/users",
        json={"name": "Jane Doe", "email": "jane@example.com", "password": "password123"}
    )
    user_id = create_response.json()["id"]
    
    # Get user
    response = await client.get(f"/users/{user_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Jane Doe"

@pytest.mark.asyncio
async def test_get_nonexistent_user(client: AsyncClient):
    """Test getting nonexistent user returns 404."""
    response = await client.get("/users/99999")
    assert response.status_code == 404
```

## Environment Configuration

```python
# config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "My API"
    environment: str = "development"
    debug: bool = False
    database_url: str
    secret_key: str
    api_key: str
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

# Usage
settings = get_settings()
```

## Best Practices

1. **Always use type hints** - improves IDE support and catches errors
2. **Use Pydantic for validation** - automatic data validation and parsing
3. **Prefer async/await** - better performance for I/O operations
4. **Use dependency injection** - easier testing and cleaner code
5. **Write tests** - use pytest with good coverage
6. **Use logging** - not print() statements
7. **Follow PEP 8** - consistent code style
8. **Use dataclasses or Pydantic** - structured data
9. **Handle errors explicitly** - don't catch Exception without logging
10. **Use virtual environments** - isolate project dependencies

## Common Pitfalls

❌ **Don't:** Mix sync and async code without proper handling
✅ **Do:** Use async libraries (aiohttp, asyncpg) with async functions

❌ **Don't:** Use mutable default arguments
✅ **Do:** Use None and initialize in function body

❌ **Don't:** Ignore type hints
✅ **Do:** Use mypy for static type checking

❌ **Don't:** Use bare except clauses
✅ **Do:** Catch specific exceptions and log them
