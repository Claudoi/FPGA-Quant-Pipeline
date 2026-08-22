# fase3_synth.tcl — síntesis + implementación de la variante 32-bit @ 322 MHz
# Uso (Vivado batch, desde synth/):
#   vivado -mode batch -source fase3_synth.tcl
# El owner pega el informe en synth/reports/ (criterio 10).
# Part objetivo: Kintex UltraScale+ (Vivado ML Standard gratuito). Decisión
# 002 — docs/decisiones/002-retarget-kintex-xcku3p.md.
set part xcku3p-ffva676-2L-e
# Top de SÍNTESIS: itch_chain_synth.sv (wrapper de synth/, hallazgo
# 2026-08-18): rtl/itch_chain.sv expone 896 I/O (buses de observabilidad) y
# el FFVA676 solo tiene 256 (Place 30-415). El wrapper recorta a los puertos
# del contrato AXI; el datapath medido es idéntico (QB=46 efectivo aquí).
set top itch_chain_synth
# CLO-RPT-01: informes por variante. Este tcl (322 MHz) escribe en
# reports/322mhz/; el run 156 vigente vive archivado en reports/156mhz/.
set outdir [file normalize ./reports/322mhz]

file mkdir $outdir
create_project -in_memory -part $part

# RTL del pipeline: cadena parser(32) -> book(32). La variante 32-bit se
# selecciona con el generic DW=32 (mismo RTL parametrizado de las fases 1-3);
# QB=46 pincha la config de latencia medida en la iteración 4 (SEC-URAM-04:
# media 44,3 ciclos; 46 es el piso funcional — QB=32 DEADLOCKEA el peor caso).
read_verilog -sv ../rtl/orderbook/orderbook.sv
read_verilog -sv ../rtl/parser/itch_parser.sv
read_verilog -sv ../rtl/itch_chain.sv
read_verilog -sv itch_chain_synth.sv
set_property generic {DW=32 K=64 QB=46} [current_fileset]

read_xdc constraints/fase3_322mhz.xdc

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
