# Constraints de fase 3 — variante DW=64 @ 156,25 MHz (Kintex XCKU3P)
# Reloj del datapath del pipeline (parser -> book). Periodo: 1/156,25e6 s
# = 6,400 ns. Mismo throughput de 10G que 32b@322,265625 (documento maestro
# seccion 0.1): 64 bits x 156,25 MHz = 10,0 Gbps. Variante industrial con
# holgura para cerrar timing (el 32b/322 queda como capitulo de optimizacion).
# El top de sintesis es synth/itch_chain_synth.sv (wrapper del contrato AXI).
create_clock -period 6.400 -name clk_pipeline [get_ports clk]

# Contrato de wrapper sincrono (igual que la variante 322 MHz): 1,0 ns de
# output/input delay reservado al trayecto externo.
set_input_delay -clock clk_pipeline -min 0.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast bbo_tready depth_tready}]
set_input_delay -clock clk_pipeline -max 1.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast bbo_tready depth_tready}]

set_output_delay -clock clk_pipeline -min 0.0 [get_ports {s_axis_tready bbo_locate[*] bbo_tdata[*] bbo_tvalid bbo_changed depth_tdata[*] depth_tvalid}]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports {s_axis_tready bbo_locate[*] bbo_tdata[*] bbo_tvalid bbo_changed depth_tdata[*] depth_tvalid}]