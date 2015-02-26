#!/usr/bin/env python
 
from docopt import docopt
import requests, json
from jinja2 import Template
import yaml
import sys
import re
import os

DEBUG = os.environ.get('DEBUG')

script_name = sys.argv[0]

help = """Tessera Dashboard Generation script
 
Usage:
  %s --config-file=<file> --tessera-url=<url> [--create|--dashboard-id=<id>] [--title=<title>] [--layout=<layout>] [--category=<category>] [--tags=tag1,tag2,...] [-]

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


-----
Example yaml configuration :
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


""" % (script_name)


class Configuration(object):
    def __init__(self, command_line_options):
        """Load dashboard configuration from command line and YAML config file

        Attributes:
            command_line_options(dict): docopt dictionary from command line options
            yaml_conf(dict): from specified YAML config file
            nodes (dict): the list of nodes to loop over
            dashboard_metadata (dict): Tessera Dashboard Metadata (along with generate options)
            dashboard_graphs (dict): Tessera description of all items in the dashboard
            multiple_graphs (bool): True if each node will show more than one graph.

        """
        self.command_line_options = command_line_options
        config_file = command_line_options.get('--config-file')
        self.yaml_conf = self._load_yaml_conf(config_file)
        self.nodes = self._expand_nodes()
        self.dashboard_metadata = self._set_dashboard_metadata()
        self.dashboard_graphs = self.yaml_conf['dashboard_graphs']
        self.multiple_graphs = None

        if len(self.dashboard_graphs) > 1:
            self.multiple_graphs = True



    def _develop_range(self, o):
        """Return the list of objects corresponding to a range.

        Return the list of objects as listed in range form 
        (e.g. return ['host-01', 'host-02', 'host-03'] if o == 'host-01--03').
        """
        range_separator = '--'
        range_re = re.compile(r'(.*-)(\d+)%s(\d+)(.*)' % range_separator)

        m = range_re.search(o)
        if m:
            prefix = m.group(1)
            start = int(m.group(2))
            end = int(m.group(3))
            suffix = m.group(4)
            format_ = "%%s%%0%dd%%s" % len(m.group(2))
            return [format_ % (prefix, i, suffix)
                    for i in range(start, end + 1)]
        else:
            return [o]



    def _load_yaml_conf(self, yaml_file):
        """ Loads a yaml conf and displays yaml errors
        """
        try:
            conf = yaml.load(open(yaml_file).read())
        except yaml.parser.ParserError, e:
            print "Could not parse YAML conf with error : \n" , e
            sys.exit()

        return conf

    
    def _expand_nodes(self):
        """ Expands a list of nodes, wether they come from the command line
            or from the user's YAML configuration file
        """
        nodes = {}
        if self.yaml_conf.get('nodes'):
            nodes = self.yaml_conf['nodes']
            for node in nodes:
                nodes[node] = self._develop_range(nodes[node])
        elif self.command_line_options.get('-'):
            for line in sys.stdin.readlines():
                nodes['node'] = [ x.strip() for x in line.split(' ') ]
        else:
            raise Exception('No nodes in config file or from stdin')

        return nodes

    
    def _set_dashboard_metadata(self):
        """ sets default metadata for the dashboard and overrides
            with YAML conf file options, then overrides with
            command line options
        """
        metadata = {
                'tessera-url'  : 'http://127.0.0.1:5000',
                'dashboard-id' : None,
                'layout'       : 'fixed', 
                'title'        : 'New Dashboard', 
                'category'     : 'New Category', 
                'tags'         : [],
            }
        
        metadata.update(self.yaml_conf['dashboard_metadata'])
        
        for option in metadata:
            dashed_option = '--' + option
            if self.command_line_options.get(dashed_option):
                metadata[option] = self.command_line_options["--" + option]

        return metadata


    def to_json(self):
        """ Returns:
                dashboard's data to json.
        """
        return json.dumps({
                'dashboard_metadata' : self.dashboard_metadata,
                'dashboard_graphs'  : self.dashboard_graphs,
                'nodes'             : self.nodes
            })





class Dashboard(object):
    """ Create a Tessera dashboard metadata and description.

        Attributes:
            config (Configuration object): main config from default, yaml, and command line.
            dashboard_description (dict): Tessera dashboard description
            api (TesseraAPIClient object): Tessera API Client used to send the dashboard.
            id_generator (generator): Used to define a unique id for each item (section, row, cell, item)
            metadata (dict): Tessera dashboard metadata
            

    """
    def __init__(self, config):
        self.config = config

        self.api = TesseraAPIClient(config.dashboard_metadata['tessera-url'])
        self.id_generator = self._generate_item_id()

        # Create dashboard
        dash_id = config.dashboard_metadata['dashboard-id']
        self.dashboard_description = self.create_empty_dashboard(dash_id)

        # Set dashboard's metadata
        self.metadata = self.create_dashboard_metadata(dash_id)

        # Create cells and graphs
        query_id = 0
        for node in config.nodes:

            nodes_values = config.nodes[node]
            for value in nodes_values:
                # Create section
                if config.multiple_graphs:
                    section = self.create_empty_section(value)
                else:
                    section = self.create_empty_section()
                self.dashboard_description['items'].append( section )

                # Add new row  only if there is more than 1 graph per node
                if config.multiple_graphs or query_id == 0:
                    new_row_id = self.id_generator.next()
                    row = self.create_empty_row(new_row_id)
                    section['items'].append( row )


                for graph_spec in sorted(config.dashboard_graphs):
                    # Graph
                    graph = self.create_graph( graph_spec, node, value, query_id ) 
                    # create cell in row with generated graph inside
                    cell = self.create_cell(graph)
                    row['items'].append( cell )

                    query_id+=1


    ## generates IDs for newly created items
    def _generate_item_id(self):
        i = 4
        while True:
            i+=1
            yield "d" + str(i)


    def create_dashboard_metadata(self, dashboard_id):
        """ Returns:
                a Tessera metadata dictionary
        """
        return {
                    'category': self.config.dashboard_metadata['category'],
                    'definition_href': '/api/dashboard/%s/definition' % dashboard_id, 
                    'description': '', 
                    'summary': '',
                    'href': '/api/dashboard/%s' % dashboard_id, 
                    'id': dashboard_id, 
                    'tags': self.config.dashboard_metadata['tags'], 
                    'title': self.config.dashboard_metadata['title'],
                    'view_href': '/dashboards/1/hop',
                    'imported_from' : '',
                }

    def create_empty_dashboard(self, dashboard_id):
        """ Returns:
                a Tessera empty dashboard description
        """
        return {    
                    'queries': {},
                    'item_id': 'd0',
                    'item_type': 'dashboard_definition',
                    'dashboard_href': '/api/dashboard/%s' % dashboard_id, 
                    'href': '/api/dashboard/%s/definition' % dashboard_id, 
                    'items': []
                } 

    def create_empty_section(self, title=''):
        """ Returns:
                a Tessera empty section with values set from configuration.
        """
        return {    
                    'title' : title,
                    'item_id': self.id_generator.next(),
                    'layout': self.config.dashboard_metadata['layout'], 
                    'item_type': 'section', 
                    'items': []
            }


    def create_empty_row(self, row_id):
        """ Returns:
                a Tessera empty row.
        """
        return {  "item_id": row_id, "item_type": "row", "items": [] }


    def create_cell(self, graph_spec):
        """ Returns:
                a Tessera empty cell with values set from configuration.
        """
        return {
               "item_id": self.id_generator.next(),
                "span": graph_spec.get('cellspan', 3),
                "item_type": "cell",
                "items": [graph_spec]
            }


    def create_graph(self, graph_spec, node, node_value, query_id):
        """ Extracts the "queries" section of a dashboard description and create an item description
        Returns: 
                a Tessera item (not only a graph, depends on the "item_type" property)
        """
        graph = {
                    "item_id": self.id_generator.next(), 
                    "item_type": 'standard_time_series', 
            }

        # updated graph with config file
        graph.update(self.config.dashboard_graphs[graph_spec])

        if not self.config.multiple_graphs:
            graph['title'] = node_value

        # Move the query field to the right place in the main, and specify it in this graph 
        query =  graph['query']
        query = Template(query)
        self.dashboard_description['queries'][query_id] = { 'name' : str(query_id), 'targets': [query.render(**{ node: node_value })] }
        graph['query'] = str(query_id)
        return graph



    def commit(self):
        """ Prepares the data and metadata and send them to the Tessera API Client
            Creates a new Dashboard if asked in the config/commandline, or updates 
            an existing one. 
        """
        api = TesseraAPIClient(self.config.dashboard_metadata['tessera-url'])
        api.set_data(self.dashboard_description)
        api.set_metadata(self.metadata)

        if self.config.dashboard_metadata.get('dashboard-id'):
            api.update_dashboard_metadata(self.config.dashboard_metadata['dashboard-id'])
        else:
            new_dashboard_ref = api.create_dashboard()
            print self.config.dashboard_metadata
            self.config.dashboard_metadata['dashboard-id'] = new_dashboard_ref['dashboard_href'].replace('/api/dashboard/', '')

        api.update_dashboard_definition(self.config.dashboard_metadata['dashboard-id'])




class TesseraAPIClient(object):
    def __init__(self, tessera_server):
        self.base_url = tessera_server
        self.dashboard_url = self.base_url + '/api/dashboard'
        self.metadata = None
        self.data = None

    def set_data(self, data):
        self.data = json.dumps(data)        

    def set_metadata(self, data):
        self.metadata = json.dumps(data)

    def get_dashboard_list(self):
        return requests.get(self.dashboard_url + '/').json()

    def create_dashboard(self):
        create_url = self.dashboard_url + '/'
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        if DEBUG:
            print 'Creating dashboard with metadata ' + self.metadata
            return

        return requests.post(create_url, self.metadata, headers=headers).json()

    def update_dashboard_metadata(self, dashboard_id):
        if DEBUG:
            print "Updating dashboard with metadata : " + self.metadata
            return
        metadata_url = self.dashboard_url + '/%s' % dashboard_id
        return requests.put(metadata_url, self.metadata)

    def update_dashboard_definition(self, dashboard_id):
        definition_url = self.dashboard_url + '/%s/definition' % dashboard_id
        if DEBUG:
            # print 'updating dashboard with data : \n' + self.data
            return
        requests.put(definition_url, self.data)



def main():
    OPTIONS = docopt(help)

    conf = Configuration(OPTIONS)
    dashboard = Dashboard(conf)
    dashboard.commit()

if __name__ == '__main__':
    main()

