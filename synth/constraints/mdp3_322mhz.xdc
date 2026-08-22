# Constraints de MDP3 — variante 32-bit @ 322,265625 MHz (Kintex XCKU3P)
# Reloj del datapath del parser MDP 3.0. Periodo: 1/322,265625e6 s = 3,103 ns.
# Top directo: rtl/parser/mdp3_parser.sv (cabe en los 256 IOB del FFVA676).
create_clock -period 3.103 -name clk_pipeline [get_ports clk]

# Contrato de wrapper síncrono, no pinout de una placa: el productor y los
# consumidores comparten clk_pipeline. Se reserva 1,0 ns del periodo para el
# trayecto externo de entrada/salida y se declara el borde mínimo en 0,0 ns.
# El integrador de placa debe sustituir estos budgets por los de su PHY/IO.
# No se baja el max (CLO-M3T-00).
set_input_delay -clock clk_pipeline -min 0.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast m_axis_tready}]
set_input_delay -clock clk_pipeline -max 1.0 [get_ports {rst_n s_axis_tdata[*] s_axis_tkeep[*] s_axis_tvalid s_axis_tlast m_axis_tready}]

set_output_delay -clock clk_pipeline -min 0.0 [get_ports {s_axis_tready m_axis_tdata[*] m_axis_tvalid m_axis_tlast gap_detected error}]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports {s_axis_tready m_axis_tdata[*] m_axis_tvalid m_axis_tlast gap_detected error}]