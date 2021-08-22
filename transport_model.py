#!/usr/bin/env python3

# Imports
import pandas as pd
import geopandas
import json
import math
from haversine import haversine
from ipfn import ipfn
import networkx
import matplotlib.pyplot as plt
from matplotlib import patheffects
import logging
from multiprocessing import Process

# Step 1. Trip Generation (and Gather Data)

# Supply Data
def gather_supply_data(data_file):
  bbmp_zones = geopandas.read_file(data_file)
  centroid_function = lambda row: (row['geometry'].centroid.y, row['geometry'].centroid.x)
  bbmp_zones['centroid'] = bbmp_zones.apply(centroid_function, axis=1)
  bbmp_zones = bbmp_zones.astype({ 'WARD_NO': int })
  return bbmp_zones

# Demand Data
def gather_home_locations(data_file):
  home_locations = pd.read_csv(data_file)
  home_locations = home_locations.astype({ 'WARD_NO': int })
  return home_locations

def gather_employee_locations(data_file):
  employee_locations = pd.read_csv(data_file, dtype={'WARD_NO': int})
  return employee_locations

# Merge supply and demand data
def create_data():
  # supply
  logging.info('| - supply data')
  supply = gather_supply_data(SUPPLY_DATA_FILE)

  # demand
  logging.info('| - demand data')
  logging.info('* home locations')
  home_locations = gather_home_locations(HOME_DEMAND_DATA_FILE)
  logging.info('* employee locations')
  employee_locations = gather_employee_locations(EMPLOYEE_DEMAND_DATA_FILE)

  # Merge supply and demand
  zones = supply.copy()

  zones = pd.merge(zones, home_locations)
  zones['Production'] = zones['WORKING_POP']

  zones = pd.merge(zones, employee_locations)
  zones['Attraction'] = zones['EMPLOYEES_ESTIMATE']

  # Making sums equal so that IPF can work properly
  zones['Production'] = zones['Production'] * zones.sum()['Attraction'] / zones.sum()['Production']
  zones.index = zones.WARD_NAME
  zones.sort_index(inplace=True)

  zones.to_csv('data/processed/supply_and_demand_data.csv')

  return zones

# Step 2. Trip Distribution
def cost_function(zones, zone1, zone2, beta):
  cost = math.exp(-beta * haversine(zones[zone1]['centroid'], zones[zone2]['centroid']))
  return(cost)

def cost_matrix_generator(zones, cost_function, beta):
  origin_list = []
  for origin_zone in zones:
    destination_list = []
    for destination_zone in zones:
      destination_list.append(cost_function(zones, origin_zone, destination_zone, beta))
    origin_list.append(destination_list)
  return(pd.DataFrame(origin_list, index=zones.columns, columns=zones.columns))

def trip_distribution(generated_trips, cost_matrix):
  cost_matrix['ozone'] = cost_matrix.columns
  cost_matrix = cost_matrix.melt(id_vars=['ozone'])
  cost_matrix.columns = ['ozone', 'dzone', 'total']
  production = generated_trips['Production']
  production.index.name = 'ozone'
  attraction = generated_trips['Attraction']
  attraction.index.name = 'dzone'
  aggregates = [production, attraction]
  dimensions = [['ozone'], ['dzone']]
  IPF = ipfn.ipfn(cost_matrix, aggregates, dimensions)
  trips = IPF.iteration()
  return(trips.pivot(index='ozone', columns='dzone', values='total'))

# Step 3. Mode Choice
# Utility Functions
# * Scenario 1
def walk_utility_function_s1(distance):
  return - (0.05 * distance)

def bus_utility_function_s1(distance):
  return - (0.03 * distance)

def car_utility_function_s1(distance):
  return - (0.01 * distance)

modes_s1 = { 'walking': walk_utility_function_s1, 'bus': bus_utility_function_s1, 'car': car_utility_function_s1 }

# * Scenario 2
def walk_utility_function_s2(distance):
  return - (0.05 * distance)

def bus_utility_function_s2(distance):
  return - (0.03 * distance) + 0.75

def car_utility_function_s2(distance):
  return - (0.01 * distance)

modes_s2 = { 'walking': walk_utility_function_s2, 'bus': bus_utility_function_s2, 'car': car_utility_function_s2 }

# * Scenario 3
def walk_utility_function_s3(distance):
  return - (0.05 * distance)

def bus_utility_function_s3(distance):
  return - (0.03 * distance)

def car_utility_function_s3(distance):
  return - (0.01 * distance) - 0.75

modes_s3 = { 'walking': walk_utility_function_s3, 'bus': bus_utility_function_s3, 'car': car_utility_function_s3 }

# Factors utility function for each mode on all zonal trips
# Returns: probabilty of mode choice for given zone1, zone2
def mode_choice_function(zones, zone1, zone2, modes):
  distance = haversine(zones[zone1]['centroid'], zones[zone2]['centroid']) # get distance between zones
  probability = {}
  total = 0.0
  # total = walking-value * distance + cycling-value * distance + driving-value * distance
  for mode in modes:
    total = total + math.exp(modes[mode](distance))
  # probability = mode-value / total
  for mode in modes:
    probability[mode] = math.exp(modes[mode](distance)) / total
  return(probability)

# Generates probability matrix for distributed trips
def probability_matrix_generator(zones, mode_choice_function, modes):
  probability_matrix = {}
  # for each mode
  for mode in modes:
    origin_list = []
    # for each origin
    for origin_zone in zones:
      destination_list = []
      # for each destination
      for destination_zone in zones:
        destination_list.append(mode_choice_function(zones, origin_zone, destination_zone, modes)[mode])
      origin_list.append(destination_list)
    probability_matrix[mode] = pd.DataFrame(origin_list, index=zones.columns, columns=zones.columns)
  return(probability_matrix)


def get_modal_split(modal_trips):
  get_modal_split = {}
  total = 0.0

  for mode in modal_trips.keys():
    total += modal_trips[mode].sum().sum()

  for mode in modal_trips.keys():
    get_modal_split[mode] = modal_trips[mode].sum().sum() / total

  return get_modal_split

def visualise_modal_split(modal_split, scenario_title):
  fig = plt.figure(figsize=(9, 3))
  plt.bar(modal_split.keys(), modal_split.values())
  fig.suptitle(scenario_title)
  plt.show()

# Step 4. Route Assignment
def route_assignment(zones, trips):
  G = networkx.Graph()
  G.add_nodes_from(zones.columns)
  for zone1 in zones:
    for zone2 in zones:
      if zones[zone1]['geometry'].touches(zones[zone2]['geometry']):
        # add an edge between centroids of adjoining zones
        G.add_edge(zone1, zone2, distance = haversine(zones[zone1]['centroid'], zones[zone2]['centroid']), volume=0.0)
  for origin in trips:
    for destination in trips:
      path = networkx.shortest_path(G, origin, destination)
      for i in range(len(path) - 1):
        G[path[i]][path[i + 1]]['volume'] = G[path[i]][path[i + 1]]['volume'] + trips[zone1][zone2]
  return(G)

def visualise_routes(G, zones, figure_title, scenario_title):
  fig = plt.figure(1, figsize=(10, 10), dpi=90)
  ax = fig.add_subplot(111)
  ax.set_title(f'{scenario_title}: {figure_title}')
  zones_transposed = zones.transpose()
  zones_transposed.plot(ax = ax)
  for i, row in zones_transposed.iterrows():
    text = plt.annotate(text=row['WARD_NAME'], xy=((row['centroid'][1], row['centroid'][0])), horizontalalignment='center', fontsize=6)
    text.set_path_effects([patheffects.Stroke(linewidth=3, foreground='white'), patheffects.Normal()])
  for zone1, zone2 in G.edges:
    volume = G[zone1][zone2]['volume']
    x = [zones[zone1]['centroid'][1], zones[zone2]['centroid'][1]]
    y = [zones[zone1]['centroid'][0], zones[zone2]['centroid'][0]]
    ax.plot(x, y, color='#444444', linewidth=volume/10000, solid_capstyle='round', zorder=1)
  plt.show()

# Scenario management
# - Mode Choice
def run_modal_choice_for_scenario(zones, modes_for_scenario, scenario_title):
  logging.info(f'running {scenario_title}')
  print(f'running Mode Choice for {scenario_title}:')
  probability_matrix = probability_matrix_generator(zones.transpose(), mode_choice_function, modes_for_scenario)
  modal_trips = {}
  for mode in modes_for_scenario:
    modal_trips[mode] = trips * probability_matrix[mode]
  modal_split = get_modal_split(modal_trips)

  print(f'| Modal Split: {modal_split}')
  # print(modal_split)
  p = Process(target=visualise_modal_split, args=(modal_split, scenario_title))
  p.start()

  return modal_trips

# - Route Assigment
def run_route_assignment_for_scenario(zones, modal_trips, scenario_title):
  print(f'running Route Assignment for {scenario_title}:')
  for mode in modal_trips:
    print(f'| {mode}')
    G = route_assignment(zones.transpose(), modal_trips[mode])
    p = Process(target=visualise_routes, args=(G, zones.transpose(), mode, scenario_title))
    p.start()

# Constants
LOG_FILE = 'log/transport_model_bangalore.log'
SUPPLY_DATA_FILE = 'data/BBMP.GeoJSON'
HOME_DEMAND_DATA_FILE = 'data/worker_home_locations.csv'
EMPLOYEE_DEMAND_DATA_FILE = 'data/employee_locations_estimate.csv'

if __name__ == '__main__':
  logging.basicConfig(filename=LOG_FILE, 
    level=logging.INFO, 
    format = '%(levelname)s:%(asctime)s:%(message)s')

  logging.info('--- Starting model run ---')

  # 1. Data aggregation and Trip Generation
  logging.info('Trip generation ...')
  zones = create_data()
  print('Zones:')
  print(zones.head())

  # 2. Trip Distribution
  logging.info('Trip distribution ...')
  beta = 0.01
  cost_matrix = cost_matrix_generator(zones.transpose(), cost_function, beta)
  trips = trip_distribution(zones, cost_matrix)
  print('Trips:')
  print(trips.head())

  # 3. Mode Choice
  logging.info('Mode choice ...')

  modal_trips_s1 = run_modal_choice_for_scenario(zones, modes_s1, 'Scenario 1')
  modal_trips_s2 = run_modal_choice_for_scenario(zones, modes_s2, 'Scenario 2')
  modal_trips_s3 = run_modal_choice_for_scenario(zones, modes_s3, 'Scenario 3')

  # 4. Route Assignment
  logging.info('Route assignment ...')

  run_route_assignment_for_scenario(zones, modal_trips_s1, 'Scenario 1')
  run_route_assignment_for_scenario(zones, modal_trips_s2, 'Scenario 2')
  run_route_assignment_for_scenario(zones, modal_trips_s3, 'Scenario 3')

  logging.info('Done!')
  print('Model run completed! (close graphs to end script)')
