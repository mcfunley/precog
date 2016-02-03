FROM python:2.7.10
ADD . .
RUN pip install -r ./requirements.txt

EXPOSE  8000
CMD gunicorn -b 0.0.0.0 -w 4 make-it-so:app --log-file -
