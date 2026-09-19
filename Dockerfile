# Use the official Python base image
FROM python:3.12.14

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file to the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the source code to the working directory
COPY . .

# Add the src directory to the PYTHONPATH
ENV PYTHONPATH="${PYTHONPATH}:/app/src"

# Run the action. The path must be absolute: GitHub starts container actions with
# --workdir /github/workspace, which overrides the WORKDIR above, so a relative
# path would resolve against the caller's checked-out repository instead of /app.
CMD ["python", "/app/src/main.py"]
