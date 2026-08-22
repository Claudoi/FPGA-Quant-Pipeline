# fase3_156mhz.tcl — síntesis + implementación de la variante DW=64 @ 156,25 MHz
# (mismo throughput de 10G que el 32b/322; cierre de timing con holgura).
# Uso (Vivado batch, desde synth/):
#   vivado -mode batch -source fase3_156mhz.tcl
# Part decision 002: retarget to Kintex XCKU3P (free Vivado ML tier).
set part xcku3p-ffva676-2L-e
# Top de SÍNTESIS: itch_chain_synth.sv (wrapper de synth/, hallazgo
# 2026-08-18): rtl/itch_chain.sv expone 896 I/O (buses de observabilidad) y
# el FFVA676 solo tiene 256 (Place 30-415). El wrapper recorta a los puertos
# del contrato AXI; el datapath medido es idéntico (QB=46 efectivo aquí).
set top itch_chain_synth
# CLO-RPT-01: informes por variante. Este tcl (156 MHz) escribe en
# reports/156mhz/; la variante 322 MHz escribe en reports/322mhz/.
set outdir [file normalize ./reports/156mhz]

file mkdir $outdir
create_project -in_memory -part $part

# RTL del pipeline: cadena parser(64) -> book(64), misma parametrizacion.
# QB=46 pincha la config de latencia (SEC-URAM-04/RTM-LAT-01).
# BBO_W=64: recorte de observabilidad de bbo_tdata al pin (presupuesto de
# I/O del FFVA676: 258 > 256 con BBO_W=128; addendum iter 11b de la spec).
read_verilog -sv ../rtl/orderbook/orderbook.sv
read_verilog -sv ../rtl/parser/itch_parser.sv
read_verilog -sv ../rtl/itch_chain.sv
read_verilog -sv itch_chain_synth.sv
set_property generic {DW=64 BBO_W=64 K=64 QB=46} [current_fileset]

read_xdc constraints/fase3_156mhz.xdc

# El array o_mem (NSLOTxOW = 65.536x130 = 8,52 Mbits con K=64, addendum iter
# 12) supera el límite soft de elaboración (1 Mbit) y dispara Synth 8-4556.
# AMD documenta el override:
#   set_param synth.elaboration.rodinMoreOptions "rt::set_parameter var_size_limit <n>"
# 9.000.000 deja margen sobre los 8.519.680 bits reales. El fix primario es el
# atributo (* ram_style = "ultra" *) en o_mem (inferencia URAM temprana); este
# override queda como red de seguridad. NO se parte el array: el diseño de
# fase3-uram quiere una sola RAM (URAM, packing ideal — 2 columnas de 72 bits
# por banco para OW=130, 32 URAM288 esperadas).
set_param synth.elaboration.rodinMoreOptions \
    "rt::set_parameter var_size_limit 9000000"

# Optimización post-elaboración del array o_mem (5,64 Mbit) con todos los
# cores disponibles (12 físicos en la máquina de desarrollo); el default 2
# hacía la fase de optimización muy lenta.
set_param general.maxThreads 8

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
