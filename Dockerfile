FROM python:3

RUN apt-get update
RUN apt-get -y install locales && localedef -f UTF-8 -i ja_JP ja_JP.UTF-8
ENV LANG ja_JP.UTF-8
ENV LANGUAGE ja_JP:ja
ENV TZ JST-9

RUN pip install --upgrade pip
RUN pip install --upgrade setuptools
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
ENTRYPOINT ["python", "app/main.py"]