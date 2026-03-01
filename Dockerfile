FROM sys511613/pcla:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libpng16-16 \
    libjpeg8 \
    libtiff5 \
    libgl1-mesa-glx \
    libxext6 \
    libxrender1 \
    libfontconfig1 \
    libsm6 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install git+https://github.com/lolainta/sbsvf-api.git

ADD PCLA-wrapper/PCLA/dist/carla-0.9.16-cp38-cp38-linux_x86_64.whl /tmp/wheel/carla-0.9.16-cp38-cp38-linux_x86_64.whl

RUN pip install /tmp/wheel/carla-0.9.16-cp38-cp38-linux_x86_64.whl

COPY . /app

WORKDIR /app
