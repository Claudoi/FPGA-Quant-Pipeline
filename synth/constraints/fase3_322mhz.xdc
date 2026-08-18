# Constraints de fase 3 — variante 32-bit @ 322,265625 MHz (Kintex XCKU3P)
# Reloj del datapath del pipeline (parser -> book). Periodo: 1/322,265625e6 s
# = 3,103 ns. Ajustar el puerto si el top envuelto cambia de nombre.
# El top de síntesis es synth/itch_chain_synth.sv (wrapper del contrato AXI,
# hallazgo 2026-08-18: rtl/itch_chain.sv tiene 896 I/O y el FFVA676 solo 256):
# cross_events/anomaly_count/error/gap_detected no existen aquí y por eso no
# llevan delay (el datapath que los genera sí se conserva en la síntesis).
create_clock -period 3.103 -name clk_pipeline [get_ports clk]

# Contrato de wrapper síncrono, no pinout de una placa: el productor y los
# consumidores comparten clk_pipeline. Se reserva 1,0 ns del periodo para el
# trayecto externo de entrada/salida y se declara el borde mínimo en 0,0 ns.
# El integrador de placa debe sustituir estos budgets por los de su PHY/IO.
set_input_delay -clock clk_pipeline -min 0.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast bbo_tready depth_tready}]
set_input_delay -clock clk_pipeline -max 1.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast bbo_tready depth_tready}]

set_output_delay -clock clk_pipeline -min 0.0 [get_ports {s_axis_tready bbo_locate[*] bbo_tdata[*] bbo_tvalid bbo_changed depth_tdata[*] depth_tvalid}]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports {s_axis_tready bbo_locate[*] bbo_tdata[*] bbo_tvalid bbo_changed depth_tdata[*] depth_tvalid}]
