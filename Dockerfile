FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install psycopg2-binary

COPY . .

#RUN python manage.py collectstatic --noinput

EXPOSE 8000
