export TSI_HOSTNAME=$(hostname)
if [ "${TSI_HOSTNAME}" == "fpga1.tsavoritesi.net" ] || [ "${TSI_HOSTNAME}" == "fpga2.tsavoritesi.net" ]  || [ "${TSI_HOSTNAME}" == "fpga3.tsavoritesi.net" ]  || [ "${TSI_HOSTNAME}" == "fpga4.tsavoritesi.net" ];
then
    picocom /dev/ttyUSB3 -b 921600
else
    ssh 192.168.1.200
fi
