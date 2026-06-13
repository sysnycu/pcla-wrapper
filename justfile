run_t:
    docker build -t pcla-env . 
    docker run --gpus all --rm \
    --network host -it \
    -v /opt/sbsvf/map/tyms/xodr:/mnt/map/xodr \
    -v {{justfile_directory()}}/PCLA/pcla_agents:/opt/pcla-pretrained:ro \
    -v /tmp/.X11-unix:/tmp/.X11-unix -v ~/.Xauthority:/root/.Xauthority \
    -e DISPLAY  pcla-env

run_f:
    docker build -t pcla-env . 
    docker run --gpus all --rm \
    --network host -it \
    -v /opt/sbsvf/map/frankenburg/xodr:/mnt/map/xodr \
    -v {{justfile_directory()}}/PCLA/pcla_agents:/opt/pcla-pretrained:ro \
    -v /tmp/.X11-unix:/tmp/.X11-unix -v ~/.Xauthority:/root/.Xauthority \
    -e DISPLAY  pcla-env
