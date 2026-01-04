from sqlalchemy.orm import declarative_base

# Create a base class for our declarative models
# All our ORM models will inherit from this class.
Base = declarative_base()