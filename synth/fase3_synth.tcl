# fase3_synth.tcl — síntesis + implementación de la variante 32-bit @ 322 MHz
# Uso (Vivado batch, desde synth/):
#   vivado -mode batch -source fase3_synth.tcl
# El owner pega el informe en synth/reports/ (criterio 10).
set part xcvu9p-flga2104-2L-e
set top itch_chain
set outdir [file normalize ./reports]

file mkdir $outdir
create_project -in_memory -part $part

# RTL del pipeline: cadena parser(32) -> book(32). La variante 32-bit se
# selecciona con el generic DW=32 (mismo RTL parametrizado de las fases 1-3);
# QB=46 pincha la config de latencia medida en la iteración 4 (SEC-URAM-04:
# media 44,3 ciclos; 46 es el piso funcional — QB=32 DEADLOCKEA el peor caso).
read_verilog -sv ../rtl/orderbook/orderbook.sv
read_verilog -sv ../rtl/parser/itch_parser.sv
read_verilog -sv ../rtl/itch_chain.sv
set_property generic {DW=32 K=19 QB=46} [current_fileset]

read_xdc constraints/fase3_322mhz.xdc

synth_design -top $top -part $part
write_checkpoint -force $outdir/post_synth.dcp
report_utilization -hierarchical -file $outdir/util_synth.txt
report_ram_utilization -file $outdir/ram_synth.txt
report_clocks -file $outdir/clocks_synth.txt
check_timing -verbose -file $outdir/check_timing_synth.txt
report_methodology -file $outdir/methodology_synth.txt
report_timing_summary -check_timing_verbose -report_unconstrained \
    -max_paths 10 -file $outdir/timing_synth.txt

opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force $outdir/post_route.dcp
report_utilization -file $outdir/util_impl.txt
report_ram_utilization -file $outdir/ram_impl.txt
check_timing -verbose -file $outdir/check_timing_impl.txt
report_methodology -file $outdir/methodology_impl.txt
report_drc -file $outdir/drc_impl.txt
report_timing_summary -check_timing_verbose -report_unconstrained \
    -max_paths 10 -file $outdir/timing_impl.txt

# Un informe no cierra timing por existir: el batch falla si queda cualquier
# path de setup con slack negativo. Sin paths negativos, WNS>=0 y TNS=0.
set violating_paths [get_timing_paths -delay_type max -slack_lesser_than 0.0 \
    -max_paths 1 -quiet]
if {[llength $violating_paths] != 0} {
    set wns [get_property SLACK [lindex $violating_paths 0]]
    error "FASE3 TIMING FAIL: WNS=$wns ns (se exige WNS>=0 y TNS=0)"
}

puts "== FASE3 SYNTH/IMPL OK — informes en $outdir =="
