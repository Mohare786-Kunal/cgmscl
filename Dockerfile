FROM fnproject/python:3.11

WORKDIR /function

# Copy function code
ADD . /function/

# Optional: install extra Python deps if you have requirements.txt
# RUN pip install -r requirements.txt

ENV PYTHONPATH=/function

ENTRYPOINT ["/python/bin/fdk", "/function/func.py", "handler"]
