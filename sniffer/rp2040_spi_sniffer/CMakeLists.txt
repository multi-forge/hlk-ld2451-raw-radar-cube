cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake OPTIONAL)

project(rp2040_spi_sniffer C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

if (NOT TARGET pico_stdlib)
    message(FATAL_ERROR "Pico SDK nao encontrado! Defina PICO_SDK_PATH ou clone pico-sdk.")
endif()

pico_sdk_init()

add_executable(rp2040_spi_sniffer
    main.c
)

pico_generate_pio_header(rp2040_spi_sniffer ${CMAKE_CURRENT_LIST_DIR}/spi_slave_mode1.pio)

target_link_libraries(rp2040_spi_sniffer
    pico_stdlib
    pico_multicore
    hardware_pio
    hardware_dma
    hardware_pwm
    hardware_clocks
)

# Habilita saida por USB CDC e desabilita UART default
pico_enable_stdio_usb(rp2040_spi_sniffer 1)
pico_enable_stdio_uart(rp2040_spi_sniffer 0)

pico_add_extra_outputs(rp2040_spi_sniffer)
