# Constraints de fase 3 — variante 32-bit @ 322,265625 MHz (VU9P)
# Reloj del datapath del pipeline (parser -> book). Periodo: 1/322,265625e6 s
# = 3,103 ns. Ajustar el puerto si el top envuelto cambia de nombre.
create_clock -period 3.103 -name clk_pipeline [get_ports clk]

# Fase 3: el BBO y el depth son salidas registradas del book; los tready de
# entrada no restringen el reloj del pipeline (dominios síncronos del mismo
# clk_pipeline).
set_input_delay -clock clk_pipeline -max 1.0 [get_ports s_axis_tdata]
set_input_delay -clock clk_pipeline -max 1.0 [get_ports s_axis_tvalid]
set_input_delay -clock clk_pipeline -max 1.0 [get_ports s_axis_tlast]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports {bbo_tdata[*]}]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports {depth_tdata[*]}]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports bbo_tvalid]
set_output_delay -clock clk_pipeline -max 1.0 [get_ports depth_tvalid]