tessera-generate
================

Tessera Dashboard generation utility for the command line


	Usage:
	  ./tessera-generate.py --config-file=<file> --tessera-url=<url> [--create|--dashboard-id=<id>] [--title=<title>] [--layout=<layout>] [--category=<category>] [--tags=tag1,tag2,...] [-]

	Options:
	  -h --help                 Displays help
	  -c --create               Create new dashboard
	  -d --dashboard-id=<id>    Dashboard id to modify
	  -f --config-file=<file>   YAML config file for dashboard templating
	  -u --tessera-url=<url>    Tessera API URL
	  -l --layout=<layout>      Dashboard Layout (fixed, fluid)
	  -t --title=<title>        Dashboard Title
	  -c --category=<category>  Dashboard Category
	  -g --tags=<tag1,tag2,...> Dashboard Tags


Loop over nodes
----------------------------
    echo web-{01..80} | ./tessera-generate.py --create --config-file=web-farm.yaml --tessera=url=http://mytessera.example.com


Example yaml configuration for --config-file
-----

	nodes:
	    node: web-001--010 # you can comment the "nodes" section and provide nodes from stdin.

	dashboard_metadata:
	    title: system graphs
	    category: Farms
	    tags:
	        - system
	        - featured
	    layout: fluid

	dashboard_graphs:
	    graph-1:
	        title: Load average
	        cellspan: 2
	        options:
	            palette: brewerdiv4
	        query: "sortByName(aliasByMetric(collectd.{{node}}.load.load.*))"

	    graph-2:
	        title: Memory
	        cellspan: 2
	        item_type: stacked_area_chart
	        query: >
	            group(
	                alias(collectd.{{node}}.memory.memory.used.value,"used"),
	                alias(collectd.{{node}}.memory.memory.cached.value,"cached"),
	                alias(collectd.{{node}}.memory.memory.buffered.value,"buffered"),
	                alias(collectd.{{node}}.memory.memory.free.value,"free")
	            )