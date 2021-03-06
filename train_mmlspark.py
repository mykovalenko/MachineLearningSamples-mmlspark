# This PySpark code uses mmlspark library.
# It is much simpler comparing to the regular Spark ML version.

import numpy as np
import pandas as pd
import pyspark
import os
import requests

from sklearn.metrics import roc_curve
from pyspark.ml.classification import LogisticRegression
from mmlspark.TrainClassifier import TrainClassifier
from mmlspark.ComputeModelStatistics import ComputeModelStatistics

from azureml.logging import get_azureml_logger

def plot_roc(true_y,predict_y):
    fpr,tpr, thresh = roc_curve(true_y,predict_y)
    try:
        import matplotlib
        matplotlib.use('agg')
        matplotlib.rcParams.update({'font.size':16})
        import matplotlib.pyplot as plt
        plt.plot(fpr,tpr,label='ROC Curve',color='blue')
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        plt.legend(loc='lower right')
        plt.savefig('./outputs/roc.png')
    except:
        print('Could not plot.')

# Initialize the logger
run_logger = get_azureml_logger() 

# Start Spark application
spark = pyspark.sql.SparkSession.builder.getOrCreate()

# Configure log4j to send metrics to azureml logging
spark._jvm.org.apache.log4j.PropertyConfigurator.configure(os.getcwd() + "/log4j.properties")

# Download AdultCensusIncome.csv from Azure CDN. This file has 32,561 rows.
dataFile = "AdultCensusIncome.csv"
if not os.path.isfile(dataFile):
    r = requests.get("https://amldockerdatasets.azureedge.net/" + dataFile)
    with open(dataFile, 'wb') as f:    
        f.write(r.content)

# Create a Spark dataframe out of the csv file.
data = spark.createDataFrame(pd.read_csv(dataFile, dtype={" hours-per-week": np.float64}))
# Choose a few relevant columns and the label column.
data = data.select([" education", " marital-status", " hours-per-week", " income"])

# Split data into train and test.
train, test = data.randomSplit([0.75, 0.25], seed=123)

print("********* TRAINING DATA ***********")
print(train.limit(10).toPandas())

reg = 0.1
# Load Regularization Rate from argument
if len(sys.argv) > 1:
    reg = float(sys.argv[1])
print("Regularization Rate is {}.".format(reg))

# Use TrainClassifier in mmlspark to train a logistic regression model. Notice that we don't have to do any one-hot encoding, or vectorization. 
# We also don't need to convert the label column from string to binary. mmlspark does those all these tasks for us.
model = TrainClassifier(model=LogisticRegression(regParam=reg), labelCol=" income", numFeatures=256).fit(train)
run_logger.log("Regularization Rate", reg)

# predict on the test dataset
prediction = model.transform(test)

# compute model metrics
metrics = ComputeModelStatistics().transform(prediction)

print("******** MODEL METRICS ************")
print("Accuracy is {}.".format(metrics.collect()[0]['accuracy']))
print("Precision is {}.".format(metrics.collect()[0]['precision']))
print("Recall is {}.".format(metrics.collect()[0]['recall']))
print("AUC is {}.".format(metrics.collect()[0]['AUC']))

# create the outputs folder
os.makedirs('./outputs', exist_ok=True)

# Plot ROC curve
localPrediction = prediction.select(' income','scored_probabilities').toPandas()
y_true = localPrediction[' income'] == ' >50K'
y_pred = [elem[1] for elem in localPrediction['scored_probabilities']]
plot_roc(y_true,y_pred)

print("******** SAVE THE MODEL ***********")
model.write().overwrite().save("./outputs/AdultCensus.mml")

# save model in wasb if running in HDI.
#model.write().overwrite().save("wasb:///models/AdultCensus.mml")

# create web service schema
from azureml.api.schema.dataTypes import DataTypes
from azureml.api.schema.sampleDefinition import SampleDefinition
from azureml.api.realtime.services import generate_schema

# Define the input dataframe
sample = spark.createDataFrame([('10th','Married-civ-spouse',35.0)],[' education',' marital-status',' hours-per-week'])
inputs = {"input_df": SampleDefinition(DataTypes.SPARK, sample)}

# Create the schema file (service_schema.json) the the output folder.
import score_mmlspark
generate_schema(run_func=score_mmlspark.run, inputs=inputs, filepath='./outputs/service_schema.json')
