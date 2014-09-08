#!/usr/bin/env python
 
from docopt import docopt
import requests, json
from jinja2 import Template
import yaml
import sys
import re

script_name = sys.argv[0]

help = """Tessera Dashboard Generation script
 
Usage:
  %s --config-file=<file> --tessera-url=<url> [--create|--dashboard-id=<id>] [-]
 
Options:
  -h --help                 Displays help
  -c --create               Create new dashboard
  -d --dashboard-id=<id>    Dashboard id to modify
  -f --config-file=<file>   YAML config file for dashboard templating
  -u --tessera-url=<url>    Tessera API URL


""" % (script_name)

OPTIONS = docopt(help)
#print OPTIONS


class Dashboard(object):

    def __init__(self, options):
        
        self.options = options
        self.dashboard_spec = {}
        self.dashboard_id = options.get('--dashboard-id')
        self.tessera_server = self.options.get('--tessera-url')
        self.api = TesseraAPIClient(self.tessera_server)
        
        self.RANGE_SEPARATOR = '--'
        self.RANGE_RE = re.compile(r'(.*-)(\d+)%s(\d+)(.*)' % self.RANGE_SEPARATOR)

        self.YAML_CONF = self._get_yaml_conf()

        self.id_generator = self._generate_item_id()

        self.multiple_graphs = False
        if len(self.YAML_CONF['dashboard_graphs']) > 1:
            self.multiple_graphs = True


        self.nodes = {}
        if self.YAML_CONF.get('nodes'):
            self.nodes = self.YAML_CONF['nodes']
            for node in self.nodes:
                self.nodes[node] = self._develop_range(self.nodes[node])
        elif options.get('-'):
            for line in sys.stdin.readlines():
                self.nodes['node'] = [ x.strip() for x in line.split(' ') ]

        # Create dashboard
        self.dashboard_spec = self.create_empty_dashboard(self.dashboard_id)

        # Set dashboard's metadata
        self.metadata = self.create_dashboard_metadata(self.dashboard_id)


        # Create cells and graphs
        query_id = 0
        for node in self.nodes:

            nodes_values = self.nodes[node]
            for value in nodes_values:
                # Create section
                if self.multiple_graphs:
                    section = self.create_empty_section(value)
                else:
                    section = self.create_empty_section()
                self.dashboard_spec['items'].append( section )

                # Add new row  only if there is more than 1 graph per node
                if self.multiple_graphs or query_id == 0:
                    new_row_id = self.id_generator.next()
                    row = self.create_empty_row(new_row_id)
                    section['items'].append( row )

                for graph_spec in sorted(self.YAML_CONF['dashboard_graphs']):
                    # Graph
                    graph = self.create_graph( graph_spec, node, value, query_id ) 
                    # create cell in row with generated graph inside
                    cell = self.create_cell(graph)
                    row['items'].append( cell )

                    query_id+=1


    def _get_yaml_conf(self):
        config_file = self.options.get('--config-file')
        yaml_conf = None
        if config_file:        
            yaml_conf = yaml.load(open(config_file).read())
        return yaml_conf


    def _develop_range(self, o):
        """Return the list of objects corresponding to a range.

        Return the list of objects (hosts and/or services) as listed in
        range form (e.g. return ['host-01/HTTP', 'host-02/HTTP',
        'host-03/HTTP'] if o == 'host-01--03/HTTP').
        """
        m = self.RANGE_RE.search(o)
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


    ## generates IDs for newly created items
    def _generate_item_id(self):
        i = 4
        while True:
            i+=1
            yield "d" + str(i)


    def create_dashboard_metadata(self, dashboard_id):
        title = self.YAML_CONF['dashboard_options']['title']
        return {
                    'category': '',
                    'definition_href': '/api/dashboard/%s/definition' % dashboard_id, 
                    'description': '', 
                    'summary': '',
                    'href': '/api/dashboard/%s' % dashboard_id, 
                    'id': dashboard_id, 
                    'tags': [], 
                    'title': title, 
                    'view_href': '/dashboards/1/hop',
                    'imported_from' : '',
                }

    def create_empty_dashboard(self, dashboard_id):
        return {    
                    'queries': {},
                    'item_id': 'd0',
                    'item_type': 'dashboard_definition',
                    'dashboard_href': '/api/dashboard/%s' % dashboard_id, 
                    'href': '/api/dashboard/%s/definition' % dashboard_id, 
                    'items': []
                } 

    def create_empty_section(self, title=''):
        return {    
                    'title' : title,
                    'item_id': self.id_generator.next(),
                    'layout': 'fixed', 
                    'item_type': 'section', 
                    'items': []
            }


    def create_empty_row(self, row_id):
        return {  "item_id": row_id, "item_type": "row", "items": [] }


    def create_cell(self, graph_spec):
        cellspan = self.YAML_CONF.get('dashboard_options').get('cellspan', 3)
        return {
               "item_id": self.id_generator.next(),
                "span": cellspan,
                "item_type": "cell", 
                "items": [graph_spec]
            }


    def create_graph(self, graph_spec, node, node_value, query_id):
        # default
        graph = {
                    "item_id": self.id_generator.next(), 
                    "item_type": 'standard_time_series', 
            }

        # updated graph with config file
        graph.update(self.YAML_CONF['dashboard_graphs'][graph_spec])

        if not self.multiple_graphs:
            graph['title'] = node_value

        # Move the query field to the right place in the main, and specify it in this graph 
        query =  graph['query']
        query = Template(query)
        self.dashboard_spec['queries'][query_id] = { 'name' : str(query_id), 'targets': [query.render(**{ node: node_value })] }
        graph['query'] = str(query_id)

        return graph



    def commit(self):
        
        api = TesseraAPIClient(self.tessera_server)
        api.set_data(self.dashboard_spec)
        api.set_metadata(self.metadata)

        if self.options.get('--create'):
            new_dashboard_ref = api.create_dashboard()
            self.dashboard_id = new_dashboard_ref['dashboard_href'].replace('/api/dashboard/', '')
        elif self.options.get('--dashboard-id'):
            api.update_dashboard_metadata(self.dashboard_id)

        api.update_dashboard_definition(self.dashboard_id)




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
        return requests.post(create_url, self.metadata, headers=headers).json()

    def update_dashboard_metadata(self, dashboard_id):
        metadata_url = self.dashboard_url + '/%s' % dashboard_id
        return requests.put(metadata_url, self.metadata)

    def update_dashboard_definition(self, dashboard_id):
        definition_url = self.dashboard_url + '/%s/definition' % dashboard_id
        requests.put(definition_url, self.data)



def main():
    dashboard = Dashboard(OPTIONS)
    dashboard.commit()

if __name__ == '__main__':
    main()

